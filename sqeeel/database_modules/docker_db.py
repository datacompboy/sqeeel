import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Callable

from .base import ExecResult, Executor


@dataclass(kw_only=True)
class DockerExecResult(ExecResult):
    """
    Represents the result of a command executed in a Docker container.
    """
    exit_code: int
    stdout: str
    stderr: str
    duration: float


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
    ):
        """
        Initializes the DockerExecutor.

        :param image_name: The name of the Docker image to use.
        :param container_name: The name to give the running container.
        :param client_command: The command and arguments to run the database client
                               inside the container (e.g., ['psql', '-U', 'user']).
        :param env: A dictionary of environment variables to set in the container.
        :param error_normalizer: A function that takes (stdout, stderr) and returns a normalized error message.
        """
        self.image_name = image_name
        self.container_name = container_name
        self.client_command = client_command
        self.env = env or {}
        self.error_normalizer = error_normalizer
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
            subprocess.run(["docker", "stop", self._container_id])
            subprocess.run(["docker", "rm", self._container_id])
            self._container_id = None

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
        
        stdout, stderr = proc.communicate(input=query)
        
        end_time = time.monotonic()
        
        duration = end_time - start_time

        error_message = None
        if proc.returncode != 0:
            if self.error_normalizer:
                error_message = self.error_normalizer(stdout, stderr)
            else:
                error_message = (stderr.strip() or stdout.strip())[:100]

        return DockerExecResult(
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration=duration,
            error_message=error_message,
        )
