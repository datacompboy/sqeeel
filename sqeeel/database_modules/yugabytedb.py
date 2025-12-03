import subprocess
import time
from typing import List, Optional

from .base import DatabaseModule, Executor
from .docker_db import DockerExecutor, DockerExecResult
from sqeeel.query_generator.generator import QueryGenerator


class YugabyteBaseExecutor(DockerExecutor):
    def __init__(self, nodes: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.nodes = nodes
        self.base_container_name = self.container_name
        self.network_name = f"{self.base_container_name}-net"
        self.container_names = []
        if nodes > 1:
            self.container_names = [f"{self.base_container_name}-{i+1}" for i in range(nodes)]
        else:
            self.container_names = [self.container_name]

    def start(self):
        if self.nodes > 1:
            # Cleanup network if exists
            subprocess.run(["docker", "network", "rm", self.network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "network", "create", self.network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        try:
            for i, name in enumerate(self.container_names):
                # Cleanup container if exists
                subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                cmd = ["docker", "run", "-d", "--name", name]
                
                if self.nodes > 1:
                    cmd.extend(["--net", self.network_name])
                
                for key, value in self.env.items():
                    cmd.extend(["-e", f"{key}={value}"])
                
                cmd.append(self.image_name)
                
                # Yugabyte start command
                yb_cmd = ["bin/yugabyted", "start", "--daemon=false"]
                if i > 0:
                    yb_cmd.append(f"--join={self.container_names[0]}")
                
                cmd.extend(yb_cmd)
                
                # print(f"Starting {name} with {cmd}")
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
                
                # Wait a bit for the first node to be ready before starting others?
                if i == 0 and self.nodes > 1:
                    time.sleep(5) 

            self.container_name = self.container_names[0]
            self._container_id = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.Id}}", self.container_name]
            ).decode("utf-8").strip()
            
        except Exception as e:
            self.stop()
            raise e

    def stop(self):
        for name in self.container_names:
            subprocess.run(["docker", "stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "rm", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if self.nodes > 1:
             subprocess.run(["docker", "network", "rm", self.network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        self._container_id = None


class YugabyteYSQLExecutor(YugabyteBaseExecutor):
    def __init__(self, image_name: str, nodes: int, container_name: str, timeout: float):
        super().__init__(
            image_name=image_name,
            nodes=nodes,
            container_name=container_name,
            client_command=["sh", "-c", "exec bin/ysqlsh -h $(hostname) -p 5433 -U yugabyte -d yugabyte --echo-all"],
            env={},
            init_queries=["CREATE TABLE IF NOT EXISTS x(x int)"],
            timeout=timeout,
            test_query="SELECT 1",
            crash_detector=self._crash_detector,
            is_query_alive_callback=self._is_query_alive,
            server_cancel_callback=self._server_cancel
        )

    def _is_query_alive(self, executor: DockerExecutor) -> Optional[str]:
        # Run a query to check if there are any active queries
        cmd = [
            "sh", "-c",
            "exec bin/ysqlsh -h $(hostname) -p 5433 -U yugabyte -d yugabyte -t -A -c \"SELECT pid FROM pg_stat_activity WHERE state='active' and pid != pg_backend_pid()\""
        ]
        try:
            stdout = executor.exec_cmd(cmd)
            result = stdout.strip()
            return result if result else None
        except Exception:
            return None

    def _server_cancel(self, executor: DockerExecutor, query_id: str):
        cmd = [
            "sh", "-c",
            f"exec bin/ysqlsh -h $(hostname) -p 5433 -U yugabyte -d yugabyte -c \"SELECT pg_cancel_backend({query_id})\""
        ]
        try:
            executor.exec_cmd(cmd)
        except Exception:
            pass

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return "server closed the connection unexpectedly" in stderr or "The connection to the server was lost" in stderr


class YugabyteYCQLExecutor(YugabyteBaseExecutor):
    def __init__(self, image_name: str, nodes: int, container_name: str, timeout: float):
        super().__init__(
            image_name=image_name,
            nodes=nodes,
            container_name=container_name,
            client_command=["sh", "-c", "exec bin/ycqlsh $(hostname) 9042"], # cqlsh usually interactive
            env={},
            init_queries=[
                "CREATE KEYSPACE IF NOT EXISTS k WITH REPLICATION = {'class': 'SimpleStrategy', 'replication_factor': 1};",
                "USE k;",
                "CREATE TABLE IF NOT EXISTS x(x int PRIMARY KEY);"
            ],
            timeout=timeout,
            test_query="SELECT now() FROM system.local;",
            # YCQL specific crash detection might differ
        )


class YugabyteModule(DatabaseModule):
    @property
    def name(self) -> str:
        return "yugabytedb"

    def configure_args(self, parser):
        parser.add_argument(
            "--db-image",
            type=str,
            default="yugabytedb/yugabyte:latest",
            help="The Docker image to use for the database.",
        )
        parser.add_argument(
            "--yb-interface",
            choices=["ysql", "ycql"],
            default="ysql",
            help="YugabyteDB interface to use (ysql or ycql).",
        )
        parser.add_argument(
            "--yb-nodes",
            type=int,
            choices=[1, 3],
            default=1,
            help="Number of nodes to start (1 or 3).",
        )

    def create_executor(self, args) -> Executor:
        if args.yb_interface == "ysql":
            return YugabyteYSQLExecutor(
                image_name=args.db_image,
                nodes=args.yb_nodes,
                container_name="sqeeel-yb-ysql",
                timeout=args.query_timeout
            )
        else:
             return YugabyteYCQLExecutor(
                image_name=args.db_image,
                nodes=args.yb_nodes,
                container_name="sqeeel-yb-ycql",
                timeout=args.query_timeout
            )

    def create_query_generator(self, grammar_file: str, max_cycle_length: int):
        return QueryGenerator(
            grammar_file,
            max_cycle_length=max_cycle_length,
            grammar_token_rewriter=self._grammar_token_rewriter,
            removed_rules=self._get_removed_rules(),
            template_token_rewriter=self._template_token_rewriter
        )

    # Copied from PostgresModule
    def _grammar_token_rewriter(self, token: str) -> str:
        replacements = {
            "EQUALS_GREATER": "=>",
            "LESS_EQUALS": "<=",
            "GREATER_EQUALS": ">=",
            "LESS_GREATER": "<>",
            "NOT_EQUALS": "!=",
            "TYPECAST": "::",
            "DOT_DOT": "..",
            "COLON_EQUALS": ":=",
            "NOT_LA": "NOT",
            "WITH_LA": "WITH",
        }
        if token in replacements:
            return replacements[token]
        
        if token.endswith("_P"):
            return token[:-2]
            
        return token

    def _get_removed_rules(self) -> List[str]:
        return ["ColId", "type_function_name", "ColLabel", "BareColLabel"]

    def _template_token_rewriter(self, token: str) -> str:
        replacements = {
            "ColId": "x x$",
            "type_function_name": "x",
            "ColLabel": "x$",
            "BareColLabel": "x$",
            "Sconst": '"1"',
            "Iconst": "0",
            "ICONST": "0",
            "FCONST": "0",
            "BCONST": 'b"0"',
            "XCONST": 'x"0"',
        }
        return replacements.get(token, token)
