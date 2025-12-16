import subprocess
import time
import uuid
import psutil
from typing import List, Optional, Callable
from .base import DatabaseModule, Executor, ExecutionStatus
from .docker_db import DockerExecutor, DockerExecResult
from sqeeel.query_generator.generator import QueryGenerator
from sqeeel.query_generator.antlr_parser import parse_antlr_grammar

class ScyllaExecutor(DockerExecutor):
    def __init__(self, nodes_count: int = 1, **kwargs):
        # cqlsh does too much of a validation, but we should test the server.
        def client_command(connect_opts: str) -> List[str]:
            client_script = ";".join((
                "import sys,cassandra.cluster",
                f"print(cassandra.cluster.Cluster(['$(hostname -i)']).connect({connect_opts}).execute(sys.stdin.read().rstrip('\\n'),timeout=None).one())"
            ))
            return ["bash", "-c", f"PYTHONPATH=$(find /opt/scylladb/ -name 'site-packages') python -c \"{client_script}\""]
        self._init_client_command = client_command("")

        super().__init__(client_command=client_command("'ks'"), **kwargs)

        self.nodes_count = nodes_count
        self.network_name = f"sqeeel-net-{uuid.uuid4().hex[:8]}"
        self.nodes = [] # List of (name, container_id)
        
        if self.nodes_count > 1:
             self.node_names = [f"{self.container_name}-{i}" for i in range(1, self.nodes_count + 1)]
        else:
             self.node_names = [self.container_name]

    def start(self):
        # Create network
        subprocess.check_call(["docker", "network", "create", "-d", "bridge", self.network_name])
        
        try:
            # Start nodes
            seed_node = self.node_names[0]
            for i, name in enumerate(self.node_names):
                cmd = [
                    "docker", "run", "-d", 
                    "--name", name, 
                    "--hostname", name, 
                    "--net", self.network_name,
                    "--cpus=2", # Restriction: 2 cores
                    self.image_name, 
                    "--smp", "2", # Scylla argument: 2 shards (cores)
                    "--memory", "1G",
                    "--overprovisioned", "1",
                    "--seeds", seed_node,
                    "--developer-mode", "1"
                ]
                
                print(f"Starting node {name}...")
                cid = subprocess.check_output(cmd).decode("utf-8").strip()
                self.nodes.append((name, cid))
                
                # Wait a bit between nodes to avoid storm
                if i == 0:
                     time.sleep(5) 
                else:
                     time.sleep(2)

            # Set the primary container ID for the base class to use (cqlsh on node 1)
            self._container_id = self.nodes[0][1]
            self.container_name = self.nodes[0][0] # Update container_name to actual running container
            
        except Exception as e:
            print(f"Failed to start ScyllaDB cluster: {e}")
            self.stop()
            raise

    def stop(self):
        for name, cid in self.nodes:
            subprocess.run(["docker", "stop", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "rm", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.nodes = []
        self._container_id = None
        
        subprocess.run(["docker", "network", "rm", self.network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _send_ns_signal(self, nspid: int, signal: str = "SIGINT"):
        """
        Sends SIGINT to the main process inside the container.
        """
        subprocess.run(["docker", "exec", self.container_name, "bash", "-c", "kill -"+signal+" "+str(nspid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _match_client_process(self, child: psutil.Process) -> Optional[int]:
        if child.cmdline()[:2] == ["python", "-c"]:
            return child.pid
        return None

    def wait_for_ready(self):
        print("Waiting for database to be ready...")
        orig_client_command = self.client_command
        self.client_command = self._init_client_command
        try:
            start_time = time.time()
            while True:
                try:
                    # Scylla might be up but CQL not ready
                    result = self.run_query("DESCRIBE CLUSTER")
                    if result.exit_code == 0:
                        break
                except Exception:
                    pass
                
                if time.time() - start_time > 120: # Scylla takes time to start
                    raise TimeoutError("Database failed to start within 120 seconds.")
                
                time.sleep(2)
                
            print("Database is ready. Running initialization queries...")
            for query in self.init_queries:
                res = self.run_query(query)
                if res.exit_code != 0:
                    # It's fine if table already exists or similar, but let's warn
                    print(f"Warning: Init query failed: {query} -> {res.error_message}")
        finally:
            self.client_command = orig_client_command

class ScyllaDBModule(DatabaseModule):
    @property
    def name(self) -> str:
        return "scylladb"

    def configure_args(self, parser):
        parser.add_argument(
            "--scylla-image",
            type=str,
            default="scylladb/scylla:latest",
            help="The Docker image to use for ScyllaDB.",
        )
        parser.add_argument(
             "--scylla-nodes",
             type=int,
             default=1,
             help="Number of ScyllaDB nodes to run."
        )

    def create_executor(self, args) -> Executor:
        return ScyllaExecutor(
            nodes_count=args.scylla_nodes,
            image_name=args.scylla_image,
            container_name="sqeeel-scylla",
            # client_command=client_command("'ks'"), # default in ScyllaExecutor
            env={},
            error_normalizer=self._normalize_error,
            init_queries=[
                "CREATE KEYSPACE IF NOT EXISTS ks WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}",
                "CREATE TABLE IF NOT EXISTS ks.x(x int PRIMARY KEY)",
            ],
            test_query="SELECT now() FROM system.local",
            timeout=args.query_timeout,
        )

    def _normalize_error(self, stdout: str, stderr: str) -> str:
        if stderr:
            lines = stderr.strip().splitlines()
            if lines:
                return lines[-1]
        return (stderr.strip() or stdout.strip())[:200]

    def create_query_generator(self, grammar_file: str, max_cycle_length: int):
        return QueryGenerator(
            grammar_file,
            max_cycle_length=max_cycle_length,
            grammar_token_rewriter=None,
            removed_rules=None,
            template_token_rewriter=self._template_token_rewriter,
            parser_func=parse_antlr_grammar
        )

    def _template_token_rewriter(self, token: str) -> str:
        if token.startswith("K_"):
            return token[2:]
            
        replacements = {
            "IDENT": "x",
            "STRING_LITERAL": "'value'",
            "INTEGER": "0",
            "FLOAT": "0.0",
            "BOOLEAN": "true",
            "UUID": "uuid()",
            "QUOTED_NAME": '"x"',
            "QMARK": "?"
        }
        return replacements.get(token, token)
