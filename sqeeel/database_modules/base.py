from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar


@dataclass
class ExecResult:
    """
    Base class for execution results.
    """
    pass


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