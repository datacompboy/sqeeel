from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqeeel.query_generator.generator import QueryGenerator

class ExecutionStatus:
    SUCCESS = "success"
    TIMEOUT = "timeout"
    HANG = "hang"
    CLIENT_HANG = "client-hang"
    CRASH = "crash"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    INTERRUPTED_HANG = "interrupted-hang"


@dataclass(kw_only=True)
class ExecResult:
    """
    Base class for execution results.
    """
    status: str = ExecutionStatus.SUCCESS
    error_message: Optional[str] = None
    duration: float = 0.0
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""


T = TypeVar("T", bound=ExecResult)


class Executor(ABC, Generic[T]):
    """
    Abstract base class for database executors.
    """

    @abstractmethod
    def start(self):
        """
        Starts the database.
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Stops the database.
        """
        pass

    def wait_for_ready(self):
        """
        Waits for the database to be ready to accept queries.
        """
        pass

    def recover(self):
        """
        Recovers the database by restarting it.
        """
        self.stop()
        self.start()
        self.wait_for_ready()

    @abstractmethod
    def run_query(self, query: str) -> T:
        """
        Runs a query on the database.
        """
        pass


class DatabaseModule(ABC):
    """
    Abstract base class for database modules.
    """

    @abstractmethod
    def create_executor(self, args) -> Executor:
        """
        Creates an executor for this database.
        """
        pass

    @abstractmethod
    def create_query_generator(self, grammar_file: str, max_cycle_length: int) -> "QueryGenerator":
        """
        Creates a configured QueryGenerator for this database.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Returns the name of the database module.
        """
        pass

    def configure_args(self, parser):
        """
        Configures the argument parser with database-specific arguments.
        """
        pass