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

        self._in_check = False
        self._detected_hang = None
        super().__init__(
            client_command=client_command("'ks'"),
            is_query_alive_callback=self._is_query_alive,
            **kwargs
        )

        self.nodes_count = nodes_count
        self.network_name = f"sqeeel-net-{uuid.uuid4().hex[:8]}"
        self.nodes = [] # List of (name, container_id)
        
        if self.nodes_count > 1:
             self.node_names = [f"{self.container_name}-{i}" for i in range(1, self.nodes_count + 1)]
        else:
             self.node_names = [self.container_name]

    def start(self):
        self._detected_hang = None
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

    def _run_health_check(self) -> Optional[str]:
        # Check 1: system_traces (global availability)
        res = self.run_query(self.test_query)
        
        if res.status == ExecutionStatus.TIMEOUT:
            return "check-timeout"
        elif res.status == ExecutionStatus.HANG:
            return "check-hang"
            
        if res.exit_code != 0:
            if "NoHostAvailable" in res.stderr and "OperationTimedOut" in res.stderr:
                return "entry-stuck"
            elif "ReadTimeout" in res.stderr:
                return "cluster-stuck"
            elif "ConnectionRefusedError" in res.stderr:
                return "node-refused"
        else:
            # Check 2: Dead nodes
            res_dead = self.run_query("SELECT up FROM system.cluster_status WHERE up = False ALLOW FILTERING BYPASS CACHE USING TIMEOUT 1s")
            if res_dead.status == ExecutionStatus.TIMEOUT:
                 return "check-dead-timeout"
                 
            # Expected stdout is "None\n" if no rows found.
            if res_dead.exit_code == 0 and res_dead.stdout.strip() != "None":
                return "node-dead"
                
        return None

    def _is_query_alive(self, executor: Executor) -> Optional[str]:
        if self._detected_hang:
            return self._detected_hang

        if self._in_check:
            return None

        self._in_check = True
        orig_timeout = self.timeout
        # We need a timeout longer than the connection/read timeouts of the driver (5s/12s)
        # to ensure we capture the error instead of timing out in docker exec.
        self.timeout = 20

        try:
            reason = self._run_health_check()
            if reason:
                self._detected_hang = reason
                return reason
        except Exception:
            pass
        finally:
            self.timeout = orig_timeout
            self._in_check = False

        return None

    def recover(self):
        print("Waiting for ScyllaDB to auto-recover...")
        # Use simple client command without keyspace for check
        orig_client_command = self.client_command
        self.client_command = self._init_client_command
        try:
            start_time = time.time()
            while time.time() - start_time < 30:
                try:
                    # Check if DB is responsive
                    if self._run_health_check() is None:
                        print("ScyllaDB auto-recovered.")
                        return
                except Exception:
                    pass
                time.sleep(1)
        finally:
            self.client_command = orig_client_command
        
        print("ScyllaDB did not auto-recover. Performing full restart.")
        super().recover()

    def wait_for_ready(self):
        print("Waiting for database to be ready...")
        orig_client_command = self.client_command
        self.client_command = self._init_client_command
        try:
            start_time = time.time()
            while True:
                try:
                    # Scylla might be up but CQL not ready
                    if self._run_health_check() is None:
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
            crash_detector=self._crash_detector,
            init_queries=[
                "CREATE KEYSPACE IF NOT EXISTS ks WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}",
                "CREATE TABLE IF NOT EXISTS ks.x(x int PRIMARY KEY)",
            ],
            # Use system_traces.sessions to check global cluster health, not just local node
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE",
            timeout=args.query_timeout,
        )

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return "ConnectionShutdown" in stderr or "ConnectionShutdown" in stdout

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
