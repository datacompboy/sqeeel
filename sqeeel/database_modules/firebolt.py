import subprocess
import time
import uuid
import json
import tempfile
import shutil
import os
from typing import List, Optional

from .base import Executor, ExecutionStatus
from .docker_db import DockerExecutor, DockerExecResult
from .postgresql import PostgresModule


class FireboltExecutor(DockerExecutor):
    def __init__(self, nodes: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.nodes = nodes
        self.base_container_name = self.container_name
        self.network_name = f"sqeeel-net-{uuid.uuid4().hex[:8]}"
        self.container_names = []
        self.host_port = None
        self.temp_dir = None
        if nodes > 1:
            self.container_names = [f"{self.base_container_name}-{i+1}" for i in range(nodes)]
        else:
            self.container_names = [self.container_name]

    def start(self):
        if self.nodes > 1:
            # Create network
            subprocess.check_call(["docker", "network", "create", "-d", "bridge", self.network_name])
            
            # Setup temp directory for config and data
            self.temp_dir = tempfile.mkdtemp(prefix="sqeeel-firebolt-")
            os.chmod(self.temp_dir, 0o777)
            
            # Create config.json
            config_path = os.path.join(self.temp_dir, "config.json")
            config_data = {
                "nodes": [{"host": name} for name in self.container_names] 
            }
            
            with open(config_path, "w") as f:
                json.dump(config_data, f)
            os.chmod(config_path, 0o644)

        try:
            for i, name in enumerate(self.container_names):
                # Cleanup container if exists
                subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                cmd = ["docker", "run", "-d", "--name", name]
                
                # Add required flags for Firebolt
                cmd.extend(["--ulimit", "memlock=8589934592:8589934592"])
                cmd.extend(["--security-opt", "seccomp=unconfined"])
                
                # Expose port for the first node (coordinator)
                if i == 0:
                    cmd.extend(["-p", "0:3473"])
                
                if self.nodes > 1:
                    assert self.temp_dir is not None
                    cmd.extend(["--net", self.network_name])
                    cmd.extend(["--hostname", name])
                    
                    # Mount config
                    cmd.extend(["-v", f"{os.path.join(self.temp_dir, 'config.json')}:/firebolt-core/config.json"])
                    
                    # Create and mount volume dir
                    vol_path = os.path.join(self.temp_dir, f"data_{i}")
                    os.makedirs(vol_path, exist_ok=True)
                    os.chmod(vol_path, 0o777)
                    cmd.extend(["-v", f"{vol_path}:/firebolt-core/volume"])
                
                for key, value in self.env.items():
                    cmd.extend(["-e", f"{key}={value}"])
                
                cmd.append(self.image_name)
                
                if self.nodes > 1:
                    # Multi-node specific argument
                    cmd.append(f"--node={i}")
                
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
                
            self.container_name = self.container_names[0]
            self._container_id = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.Id}}", self.container_name]
            ).decode("utf-8").strip()

            # Find the assigned host port
            inspect_cmd = ["docker", "inspect", self.container_name]
            inspect_output = subprocess.check_output(inspect_cmd).decode("utf-8")
            container_info = json.loads(inspect_output)[0]
            ports = container_info["NetworkSettings"]["Ports"]
            # 3473/tcp
            if "3473/tcp" in ports and ports["3473/tcp"]:
                self.host_port = ports["3473/tcp"][0]["HostPort"]
            else:
                raise RuntimeError("Failed to map container port 3473 to host.")

        except Exception as e:
            print(f"Failed to start Firebolt cluster: {e}")
            self.stop()
            raise

    def stop(self):
        for name in self.container_names:
            subprocess.run(["docker", "stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "rm", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if self.nodes > 1:
            subprocess.run(["docker", "network", "rm", self.network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Cleanup temp dir
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                self.temp_dir = None
        
        self._container_id = None
        self.host_port = None

    def run_query(self, query: str) -> DockerExecResult:
        if not self.host_port:
            raise RuntimeError("Database is not started or port not mapped.")

        clean_query = query.strip()
        
        # Construct curl command
        # curl -s --fail-with-body "http://localhost:<PORT>/" --data-binary @-
        cmd = [
            "curl", "-s", "--fail-with-body",
            f"http://localhost:{self.host_port}/",
            "--data-binary", "@-"
        ]
        
        result = self._execute_process(cmd, clean_query)

        if result.exit_code == 22:
             result.status = ExecutionStatus.ERROR
             out_str = result.stdout.strip()
             if out_str.startswith("{"):
                 try:
                     err_json = json.loads(out_str)
                     if "errors" in err_json and err_json["errors"]:
                         desc = err_json["errors"][0]["description"]
                         msg = desc.splitlines()[0] if desc else ""
                         if msg.startswith("Line 1, Column "):
                            msg = msg.split(":", 1)[1].strip()
                         result.error_message = msg
                     else:
                         result.error_message = out_str
                 except Exception:
                     result.error_message = out_str
             else:
                 result.error_message = out_str
        
        return result

    def wait_for_ready(self):
        print("Waiting for database to be ready...")
        # Check that all cluster nodes are actually running
        for name in self.container_names:
            if not self._is_container_running_name(name):
                logs = ""
                try:
                    logs = subprocess.check_output(["docker", "logs", name]).decode()[-1000:]
                except Exception:
                    pass
                raise RuntimeError(f"Container {name} crashed or exited unexpectedly.\nLogs:\n{logs}")
        
        start_time = time.time()
        while True:
            try:
                result = self.run_query("SELECT 1")
                if result.exit_code == 0 and "1" in result.stdout:
                    break
            except Exception:
                pass
            
            if time.time() - start_time > 60:
                raise TimeoutError("Database failed to start within 60 seconds.")
            
            time.sleep(1)
            
        print("Database is ready. Running initialization queries...")
        for query in self.init_queries:
            res = self.run_query(query)
            if res.exit_code != 0:
                raise RuntimeError(f"Initialization query failed: {query}\nError: {res.error_message}")

    def _is_container_running_name(self, name: str) -> bool:
        try:
             cmd = ["docker", "inspect", "-f", "{{.State.Running}}", name]
             out = subprocess.check_output(cmd, text=True).strip()
             return out == "true"
        except subprocess.CalledProcessError:
             return False


class FireboltModule(PostgresModule):
    @property
    def name(self) -> str:
        return "firebolt"

    def configure_args(self, parser):
        parser.add_argument(
            "--db-image",
            type=str,
            default="ghcr.io/firebolt-db/firebolt-core:preview-rc",
            help="The Docker image to use for the database.",
        )
        parser.add_argument(
            "--firebolt-nodes",
            type=int,
            choices=[1, 3],
            default=1,
            help="Number of nodes to start (1 or 3).",
        )

    def create_executor(self, args) -> Executor:
        return FireboltExecutor(
            nodes=args.firebolt_nodes,
            image_name=args.db_image,
            container_name="sqeeel-test-db-firebolt",
            client_command=["true"],
            env={"POSTGRES_PASSWORD": "mysecretpassword"},
            error_normalizer=self._normalize_error,
            init_queries=["CREATE TABLE IF NOT EXISTS x(x int)"],
            timeout=args.query_timeout,
            terminate_query_callback=lambda p: p.kill(),
            is_query_alive_callback=self._is_query_alive,
            server_cancel_callback=self._server_cancel,
            crash_detector=self._crash_detector
        )

    def _is_query_alive(self, executor: DockerExecutor) -> Optional[str]:
        # SELECT query_id FROM information_schema.engine_running_queries where e2e_duration_us>1000000;
        cmd = "SELECT query_id FROM information_schema.engine_running_queries where e2e_duration_us>1000000;"
        try:
            res = executor.run_query(cmd)
            if res.exit_code == 0 and res.stdout:
                # Parse output. Default format:
                # query_id
                # text null
                # 478de3d9-cc1f-49e7-a983-98765f9d1d7a
                lines = res.stdout.strip().splitlines()
                if len(lines) > 2:
                    # Skip header and type lines
                    return lines[2].strip()
        except Exception:
            pass
        return None

    def _server_cancel(self, executor: DockerExecutor, query_id: str):
        # cancel query where query_id='${query_id}';
        cmd = f"cancel query where query_id='{query_id}';"
        try:
            executor.run_query(cmd)
        except Exception:
            pass
