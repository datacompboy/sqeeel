import re
import time
from typing import Optional, List
from .base import Executor
from .docker_db import DockerExecutor
from .mariadb import MariaDBModule

class SingleStoreExecutor(DockerExecutor):
    def __init__(self, **kwargs):
        super().__init__(
            is_query_alive_callback=self._is_query_alive,
            server_cancel_callback=self._server_cancel,
            crash_detector=self._crash_detector,
            **kwargs
        )

    def _is_query_alive(self, executor: DockerExecutor) -> Optional[str]:
        # SingleStore uses information_schema.processlist like MySQL/MariaDB
        cmd = [
            "memsql", "-h", "127.0.0.1", "-P", "3306", "-u", "root", "-N", "-s", "-e",
            "SELECT id FROM information_schema.processlist WHERE command != 'Sleep' AND id != CONNECTION_ID()"
        ]
        
        try:
            stdout = self.exec_cmd(cmd)
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
            self.exec_cmd(cmd)
            # Wait a bit to let the query cancel take effect
            for k in range(10):
                if not self._is_query_alive(self):
                    return
                time.sleep(1)
        except Exception:
            pass

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return "Lost connection to MySQL server" in stderr or "Can't connect to MySQL server" in stderr or "ERROR 2013" in stderr

    def recover(self):
        print("Waiting for SingleStore to auto-recover...")
        # Try for 30 seconds
        start_time = time.time()
        while time.time() - start_time < 30:
            try:
                res = self.run_query("SELECT 1")
                if res.exit_code == 0:
                    print("SingleStore auto-recovered.")
                    return
            except Exception:
                pass
            time.sleep(1)
        
        print("SingleStore did not auto-recover. Performing full restart.")
        super().recover()


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
        return SingleStoreExecutor(
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
        )

    def _normalize_error(self, stdout: str, stderr: str) -> str:
        msg = super()._normalize_error(stdout, stderr)
        # Normalize thread stack overrun error
        # "Used: 1287168 of a 1048576 stack" -> "Used: X of a 1048576 stack"
        msg = re.sub(r"Used: \d+ of a", "Used: X of a", msg)
        return msg
