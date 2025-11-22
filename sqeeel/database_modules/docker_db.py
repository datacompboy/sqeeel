import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Callable

from .base import ExecResult, Executor, ExecutionStatus


@dataclass(kw_only=True)
class DockerExecResult(ExecResult):
    """
    Represents the result of a command executed in a Docker container.
    """


class DockerExecutor(Executor[DockerExecResult]):
    """
    An executor that runs a database in a Docker container and executes queries
    using 'docker exec'.
    """

    def __init__(
        self,
        image_name: str,
        container_name: str,
        client_command: List[str],
        env: Optional[dict] = None,
        error_normalizer: Optional[Callable[[str, str], str]] = None,
        test_query: str = "SELECT 1",
        init_queries: Optional[List[str]] = None,
        timeout: Optional[float] = None,
        terminate_query_callback: Optional[Callable[[subprocess.Popen], None]] = None,
        is_query_alive_callback: Optional[Callable[["DockerExecutor"], bool]] = None,
        crash_detector: Optional[Callable[[str, str], bool]] = None,
    ):
        """
        Initializes the DockerExecutor.

        :param image_name: The name of the Docker image to use.
        :param container_name: The name to give the running container.
        :param client_command: The command and arguments to run the database client
                               inside the container (e.g., ['psql', '-U', 'user']).
        :param env: A dictionary of environment variables to set in the container.
        :param error_normalizer: A function that takes (stdout, stderr) and returns a normalized error message.
        :param test_query: A query to run to check if the database is ready.
        :param init_queries: A list of queries to run after the database is ready.
        :param timeout: The timeout for query execution in seconds.
        :param terminate_query_callback: Callback to terminate the query (takes proc).
        :param is_query_alive_callback: Callback to check if query is alive (takes self).
        :param crash_detector: Callback to detect crash from stdout/stderr.
        """
        self.image_name = image_name
        self.container_name = container_name
        self.client_command = client_command
        self.env = env or {}
        self.error_normalizer = error_normalizer
        self.test_query = test_query
        self.init_queries = init_queries or []
        self.timeout = timeout
        self.terminate_query_callback = terminate_query_callback
        self.is_query_alive_callback = is_query_alive_callback
        self.crash_detector = crash_detector
        self._container_id: Optional[str] = None

    def start(self):
        """
        Starts the database container.
        """
        cmd = ["docker", "run", "-d", "--name", self.container_name]
        for key, value in self.env.items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.append(self.image_name)
        
        try:
            self._container_id = subprocess.check_output(cmd).decode("utf-8").strip()
        except subprocess.CalledProcessError as e:
            print(f"Failed to start container: {e.stderr}")
            raise

    def stop(self):
        """
        Stops and removes the database container.
        """
        if self._container_id:
            subprocess.run(["docker", "stop", self._container_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "rm", self._container_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._container_id = None

    def wait_for_ready(self):
        print("Waiting for database to be ready...")
        start_time = time.time()
        while True:
            try:
                result = self.run_query(self.test_query)
                if result.exit_code == 0:
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

    def exec_cmd(self, args: List[str], input_text: Optional[str] = None) -> str:
        """
        Executes a raw command in the container.
        """
        if not self._container_id:
            raise RuntimeError("Container is not running.")

        cmd = ["docker", "exec", "-i", self._container_id] + args
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = proc.communicate(input=input_text)
        if proc.returncode != 0:
             # Can't easily differentiate why it failed, just return output for now or raise?
             # For checking logic, we might want the output.
             pass
        return stdout

    def run_query(self, query: str) -> DockerExecResult:
        """
        Runs a query inside the container using 'docker exec'.

        :param query: The SQL query to execute.
        :return: A DockerExecResult with the execution details.
        """
        if not self._container_id:
            raise RuntimeError("Container is not running. Call start() first.")

        cmd = ["docker", "exec", "-i", self._container_id] + self.client_command
        
        start_time = time.monotonic()
        
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        stdout = ""
        stderr = ""
        exit_code = None
        status = ExecutionStatus.SUCCESS
        
        try:
            stdout, stderr = proc.communicate(input=query, timeout=self.timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            # 1. Terminate
            if self.terminate_query_callback:
                self.terminate_query_callback(proc)
            else:
                proc.kill()
            
            # 2. Wait
            time.sleep(2)
            
            # 3. Check alive
            try:
                is_alive = False
                if self.is_query_alive_callback:
                    is_alive = self.is_query_alive_callback(self)
                else:
                    # Fallback: check if process is still running
                    is_alive = (proc.poll() is None)
                
                if is_alive:
                    status = ExecutionStatus.HANG
                else:
                    status = ExecutionStatus.TIMEOUT
            except Exception:
                 status = ExecutionStatus.CRASH

            # Cleanup if still running (force kill if fallback/logic failed to kill it)
            if proc.poll() is None:
                 proc.kill()
                 proc.wait()

            try:
                stdout = proc.stdout.read() if proc.stdout else "" # might be closed/consumed
                stderr = proc.stderr.read() if proc.stderr else ""
            except ValueError:
                # file might be closed
                pass

        end_time = time.monotonic()
        duration = end_time - start_time

        error_message = None
        
        if status == ExecutionStatus.SUCCESS:
            if self.crash_detector and self.crash_detector(stdout, stderr):
                status = ExecutionStatus.CRASH

            if exit_code != 0:
                if self.error_normalizer:
                    error_message = self.error_normalizer(stdout, stderr)
                else:
                    error_message = (stderr.strip() or stdout.strip())[:100]

        return DockerExecResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration=duration,
            error_message=error_message,
            status=status
        )
