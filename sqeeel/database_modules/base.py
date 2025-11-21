from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar, TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqeeel.query_generator.generator import QueryGenerator

@dataclass(kw_only=True)
class ExecResult:
    """
    Base class for execution results.
    """
    error_message: Optional[str] = None


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