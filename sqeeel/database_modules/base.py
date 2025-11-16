"""
Base class for database modules.
"""

class DatabaseModule:
    """
    Base class for database-specific modules.
    """
    def __init__(self, config):
        self.config = config

    def start(self):
        """
        Start the database engine.
        """
        raise NotImplementedError

    def stop(self):
        """
        Stop the database engine.
        """
        raise NotImplementedError

    def run_query(self, query):
        """
        Run a query and measure its impact.
        """
        raise NotImplementedError

    def get_language_tuning(self):
        """
        Get language tuning information for the query templates generator.
        """
        raise NotImplementedError