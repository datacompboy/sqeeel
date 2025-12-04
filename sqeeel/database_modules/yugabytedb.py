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
                
                # If distributed, wait for each node to be ready before proceeding to the next
                # This ensures stable clustering
                if self.nodes > 1:
                    print(f"Waiting for {name} to be ready...")
                    ready = False
                    for _ in range(60):
                        time.sleep(1)
                        if self._is_node_ready(name):
                            ready = True
                            break
                    if not ready:
                        raise RuntimeError(f"Node {name} failed to become ready.")

            self.container_name = self.container_names[0]
            self._container_id = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.Id}}", self.container_name]
            ).decode("utf-8").strip()
            
        except Exception as e:
            self.stop()
            raise e

    def _is_node_ready(self, container_name: str) -> bool:
        cmd = ["docker", "exec", container_name, "bin/yugabyted", "status"]
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode()
            for line in output.splitlines():
                if "Status" in line and "Running" in line:
                    return True
            return False
        except Exception:
            return False

    def wait_for_ready(self):
        # Check that all cluster nodes are actually running
        for name in self.container_names:
            if not self._is_container_running_name(name):
                logs = ""
                try:
                    logs = subprocess.check_output(["docker", "logs", name]).decode()[-1000:]
                except Exception:
                    pass
                raise RuntimeError(f"Container {name} crashed or exited unexpectedly.\nLogs:\n{logs}")
        
        super().wait_for_ready()

    def _is_container_running_name(self, name: str) -> bool:
        try:
             cmd = ["docker", "inspect", "-f", "{{.State.Running}}", name]
             out = subprocess.check_output(cmd, text=True).strip()
             return out == "true"
        except subprocess.CalledProcessError:
             return False

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
                "CREATE TABLE IF NOT EXISTS x(x int PRIMARY KEY);"
            ],
            timeout=timeout,
            test_query="SELECT now() FROM system.local;",
            terminate_query_callback=self._terminate_client,
            is_query_alive_callback=self._is_client_alive,
            server_cancel_callback=self._force_kill_client,
            crash_detector=self._crash_detector
        )

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return (
            "ConnectionShutdown" in stderr or
            "ConnectionRefusedError" in stderr or
            "NoHostAvailable" in stderr or
            "Connection to" in stderr and "was closed" in stderr
        )

    def _get_client_pid(self, executor: DockerExecutor) -> Optional[str]:
        cmd = ["pgrep", "-f", "ycqlsh.py"]
        try:
            stdout = executor.exec_cmd(cmd)
            result = stdout.strip()
            return result.splitlines()[0] if result else None
        except Exception:
            return None

    def _terminate_client(self, proc):
        pid = self._get_client_pid(self)
        if pid:
            cmd = ["kill", "-SIGINT", pid]
            try:
                self.exec_cmd(cmd)
            except Exception:
                pass
        
        try:
            proc.terminate()
        except Exception:
            pass

    def _is_client_alive(self, executor: DockerExecutor) -> Optional[str]:
        return self._get_client_pid(executor)

    def _force_kill_client(self, executor: DockerExecutor, query_id: str):
        cmd = ["kill", "-9", query_id]
        try:
            executor.exec_cmd(cmd)
        except Exception:
            pass

    def run_query(self, query: str) -> DockerExecResult:
        # Force semicolon
        clean_query = query.strip()
        if clean_query and not clean_query.endswith(";"):
            clean_query += ";"
        
        # Prepend USE k; to generated queries to handle session isolation
        # Skip for test_query (k might not exist yet) and CREATE KEYSPACE
        if query != self.test_query and not clean_query.lower().startswith("create keyspace"):
            clean_query = "USE k; " + clean_query

        result = super().run_query(clean_query)
        
        # YCQL client might exit with 0 even on error, so we check stderr
        if result.exit_code == 0 and result.status == "success" and result.stderr:
            # Any stderr output means error for YCQL
            result.exit_code = 1
            # Keep only the first line of stderr
            lines = result.stderr.strip().splitlines()
            result.error_message = lines[0] if lines else ""
        
        return result


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
