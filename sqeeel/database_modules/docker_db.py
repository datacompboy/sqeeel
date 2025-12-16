import subprocess
import time
import psutil
import os
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
        is_query_alive_callback: Optional[Callable[["DockerExecutor"], Optional[str]]] = None,
        server_cancel_callback: Optional[Callable[["DockerExecutor", str], None]] = None,
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
        :param is_query_alive_callback: Callback to check if query is alive (takes self, returns ID).
        :param server_cancel_callback: Callback to cancel query on server (takes self, ID).
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
        self.server_cancel_callback = server_cancel_callback
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
             raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)
        return stdout

    def _get_nspid(self, pid: int) -> Optional[int]:
        try:
            with open(f"/proc/{pid}/status", "r") as f:
                for line in f:
                    if line.startswith("NSpid:"):
                        # Format: NSpid:  524212  209
                        parts = line.split()
                        return int(parts[-1])
        except Exception:
            pass
        return None

    def _is_container_running(self) -> bool:
        try:
             cmd = ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name]
             out = subprocess.check_output(cmd, text=True).strip()
             return out == "true"
        except subprocess.CalledProcessError:
             return False

    def _send_ns_signal(self, nspid: int, signal: str = "SIGINT"):
        """
        Sends SIGINT to the main process inside the container.
        """
        subprocess.run(["docker", "exec", self.container_name, "kill", "-"+signal, str(nspid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _match_client_process(self, child: psutil.Process) -> Optional[int]:
        if child.cmdline() == self.client_command:
            return child.pid
        return None

    def _client_cancel(self):
        """
        Sends SIGINT to the process inside the container.
        """
        try:
            # 1. Get container main PID
            cmd = ["docker", "inspect", "-f", "{{.State.Pid}}", self.container_name]
            container_pid_str = subprocess.check_output(cmd, text=True).strip()
            container_pid = int(container_pid_str)

            # 2. Get PPid of container process (shim)
            try:
                p = psutil.Process(container_pid)
                shim_pid = p.ppid()
            except psutil.NoSuchProcess:
                return

            # 3. Find siblings (children of shim) that match our client
            target_pid = None
            shim_proc = psutil.Process(shim_pid)
            for child in shim_proc.children(recursive=False):
                if child.pid == container_pid:
                    continue
                
                try:
                    # Match command name. Note: this is a heuristic.
                    if target_pid := self._match_client_process(child):
                         break
                except psutil.NoSuchProcess:
                    continue

            if target_pid:
                nspid = self._get_nspid(target_pid)
                if nspid:
                    self._send_ns_signal(nspid, "SIGINT")
        except Exception:
            pass

    def run_query(self, query: str) -> DockerExecResult:
        """
        Runs a query inside the container using 'docker exec'.

        :param query: The SQL query to execute.
        :return: A DockerExecResult with the execution details.
        """
        if not self._container_id:
            raise RuntimeError("Container is not running. Call start() first.")

        cmd = ["docker", "exec", "-i", self._container_id] + self.client_command
        return self._execute_process(cmd, query)

    def _execute_process(self, cmd: List[str], input_text: str) -> DockerExecResult:
        start_time = time.monotonic()
        
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        stdout = ""
        stderr = ""
        exit_code = None
        status = ExecutionStatus.SUCCESS
        
        try:
            stdout, stderr = proc.communicate(input=input_text, timeout=self.timeout)
            exit_code = proc.returncode
            end_time = time.monotonic()
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as e:
            is_interrupt = isinstance(e, KeyboardInterrupt)
            end_time = time.monotonic()
            # 1. Client cancel
            if self.terminate_query_callback:
                self.terminate_query_callback(proc)
            else:
                self._client_cancel()

            # 2. Wait for cancel if possible
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                pass

            # 3. Check currently running query Id
            query_id = None
            try:
                if self.is_query_alive_callback:
                    query_id = self.is_query_alive_callback(self)
                
                if not query_id:
                    # All good, query was just in status 'timeout'
                    status = ExecutionStatus.TIMEOUT
                else:
                    # The query is at least in 'client-hung' state
                    # 4. Server-side cancel
                    if self.server_cancel_callback:
                        self.server_cancel_callback(self, query_id)
                    
                    # 5. Sleep for 2 seconds
                    time.sleep(2)
                    
                    # 6. Check currently running query Id again
                    query_id_after = None
                    if self.is_query_alive_callback:
                        query_id_after = self.is_query_alive_callback(self)
                    
                    if not query_id_after:
                         # 'client-hung' is the final state, no recovery needed.
                         status = ExecutionStatus.CLIENT_HANG
                    else:
                         # 'server-hung' is the query final state
                         status = ExecutionStatus.HANG

            except Exception:
                 status = ExecutionStatus.CRASH

            # Cleanup if still running (force kill if fallback/logic failed to kill it)
            if proc.poll() is None:
                 proc.kill()
                 stdout, stderr = proc.communicate(timeout=2)
                 proc.wait()

            try:
                stdout = proc.stdout.read() if proc.stdout else "" # might be closed/consumed
                stderr = proc.stderr.read() if proc.stderr else ""
            except ValueError:
                # file might be closed
                pass
            
            if not self._is_container_running():
                status = ExecutionStatus.CRASH

            if is_interrupt:
                if status in [ExecutionStatus.HANG, ExecutionStatus.CRASH]:
                    status = ExecutionStatus.INTERRUPTED_HANG
                else:
                    status = ExecutionStatus.INTERRUPTED

        duration = end_time - start_time

        if len(stdout) > 11005:
            stdout = stdout[:10000] + "..." + stdout[-1000:]
        if len(stderr) > 11005:
            stderr = stderr[:10000] + "..." + stderr[-1000:]

        error_message = None
        
        if status == ExecutionStatus.SUCCESS:
            if "Error response from daemon:" in stderr and "is not running" in stderr:
                raise RuntimeError(f"Critical Docker failure: {stderr.strip()}")

            if exit_code == 137:
                status = ExecutionStatus.CRASH
            elif self.crash_detector and self.crash_detector(stdout, stderr):
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
