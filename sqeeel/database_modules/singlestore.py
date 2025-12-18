import re
from typing import Optional, List
from .base import Executor
from .docker_db import DockerExecutor
from .mariadb import MariaDBModule

class SingleStoreModule(MariaDBModule):
    @property
    def name(self) -> str:
        return "singlestore"

    def configure_args(self, parser):
        parser.add_argument(
            "--db-image",
            type=str,
            default="singlestore/cluster-in-a-box:latest",
            help="The Docker image to use for the database.",
        )

    def create_executor(self, args) -> Executor:
        return DockerExecutor(
            image_name=args.db_image,
            container_name="sqeeel-test-db-singlestore",
            client_command=["memsql", "-h", "127.0.0.1", "-P", "3306", "-u", "root", "--init-command=CREATE DATABASE IF NOT EXISTS testdb; USE testdb"],
            env={
                "ROOT_PASSWORD": "mysecretpassword",
                "START_AFTER_INIT": "Y",
                "MYSQL_PWD": "mysecretpassword"
            },
            error_normalizer=self._normalize_error,
            test_query="SELECT 1", 
            init_queries=[
                "CREATE TABLE IF NOT EXISTS x(x int)"
            ],
            timeout=args.query_timeout,
            is_query_alive_callback=self._is_query_alive,
            server_cancel_callback=self._server_cancel,
            crash_detector=self._crash_detector
        )

    def _is_query_alive(self, executor: DockerExecutor) -> Optional[str]:
        # SingleStore uses information_schema.processlist like MySQL/MariaDB
        cmd = [
            "memsql", "-h", "127.0.0.1", "-P", "3306", "-u", "root", "-N", "-s", "-e",
            "SELECT id FROM information_schema.processlist WHERE command != 'Sleep' AND id != CONNECTION_ID()"
        ]
        
        try:
            # Pass password via env for this command too? 
            # DockerExecutor.exec_cmd just runs `docker exec`. 
            # We need to set env inside the container command if not set globally in container.
            # But the 'env' in DockerExecutor is for 'docker run -e'.
            # For 'docker exec', we can't easily pass env vars unless we wrap in sh -c.
            # BUT, we can just export it in the command list if we wrap it.
            # OR, simpler: just rely on MYSQL_PWD being set in the container if we add it to 'env' of start()
            # Wait, DockerExecutor.env is passed to `docker run`. So MYSQL_PWD will be set in the container environment.
            # So `memsql` inside the container should pick it up!
            stdout = executor.exec_cmd(cmd)
            result = stdout.strip()
            return result if result else None
        except Exception:
            return None

    def _server_cancel(self, executor: DockerExecutor, query_id: str):
        cmd = [
            "memsql", "-h", "127.0.0.1", "-P", "3306", "-u", "root", "-e",
            f"KILL QUERY {query_id}"
        ]
        try:
            executor.exec_cmd(cmd)
        except Exception:
            pass

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return "Lost connection to MySQL server" in stderr or "Can't connect to MySQL server" in stderr or "ERROR 2013" in stderr

    def _normalize_error(self, stdout: str, stderr: str) -> str:
        msg = super()._normalize_error(stdout, stderr)
        # Normalize thread stack overrun error
        # "Used: 1287168 of a 1048576 stack" -> "Used: X of a 1048576 stack"
        msg = re.sub(r"Used: \d+ of a", "Used: X of a", msg)
        return msg
