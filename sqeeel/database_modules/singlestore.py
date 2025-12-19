import re
import time
import subprocess
from typing import Optional, List
from .base import Executor, ExecutionStatus
from .docker_db import DockerExecutor, DockerExecResult
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
        
        # We do NOT want to swallow connection errors here.
        # If exec_cmd raises (e.g. connection refused), let it bubble up
        # so DockerExecutor marks it as CRASH.
        try:
            stdout = self.exec_cmd(cmd)
            result = stdout.strip()
            return result if result else None
        except subprocess.CalledProcessError as e:
            # If the error is not about connection, maybe it's fine?
            # But failure to check processlist usually means big trouble.
            raise e

    def _server_cancel(self, executor: DockerExecutor, query_id: str):
        cmd = [
            "memsql", "-h", "127.0.0.1", "-P", "3306", "-u", "root", "-e",
            f"KILL QUERY {query_id}"
        ]
        try:
            self.exec_cmd(cmd)
            # Wait a bit to let the query cancel take effect
            for k in range(10):
                # If checking query alive fails (crash), we stop waiting
                try:
                    if not self._is_query_alive(self):
                        return
                except Exception:
                    return
                time.sleep(1)
        except Exception:
            pass

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        err = stdout + stderr
        if "Lost connection to MySQL server" in err or "Can't connect to MySQL server" in err or "ERROR 2013" in err:
            return True
        # "waiting for the Master Aggregator" -> code 2269
        if "ERROR 2269" in err or "waiting for the Master Aggregator" in err:
            return True
        return False

    def run_query(self, query: str) -> DockerExecResult:
        res = super().run_query(query)
        
        # If query failed (or timed out), ensure the server is actually healthy.
        # User reported cases where status is TIMEOUT but server is crashing.
        if res.status != ExecutionStatus.SUCCESS:
            if not self._check_health():
                res.status = ExecutionStatus.CRASH
                res.error_message = (res.error_message or "") + " [Server unhealthy]"
        
        return res

    def _check_health(self) -> bool:
        try:
            # Run a simple check. If this fails (raises or non-zero exit), assume unhealthy.
            # We use super().run_query to avoid recursion (though run_query doesn't call itself)
            # but mainly to get a DockerExecResult
            check_res = super().run_query(self.test_query)
            if check_res.exit_code != 0:
                return False
            # Also check for critical errors in the output even if exit code is 0 (unlikely but safe)
            if self._crash_detector(check_res.stdout, check_res.stderr):
                return False
            return True
        except Exception:
            return False

    def recover(self):
        print("Waiting for SingleStore to auto-recover...")
        # Try for 30 seconds
        start_time = time.time()
        while time.time() - start_time < 30:
            if self._check_health():
                # Server seems up. Wait a bit to ensure stability (watchdog delay).
                time.sleep(5)
                if self._check_health():
                    print("SingleStore auto-recovered.")
                    return
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
