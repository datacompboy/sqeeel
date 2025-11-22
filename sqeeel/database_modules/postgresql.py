import re
from typing import Optional, List
from .base import DatabaseModule, Executor
from .docker_db import DockerExecutor
from sqeeel.query_generator.generator import QueryGenerator

class PostgresModule(DatabaseModule):
    @property
    def name(self) -> str:
        return "postgres"

    def configure_args(self, parser):
        parser.add_argument(
            "--db-image",
            type=str,
            default="postgres:latest",
            help="The Docker image to use for the database.",
        )

    def create_executor(self, args) -> Executor:
        return DockerExecutor(
            image_name=args.db_image,
            container_name="sqeeel-test-db-postgres",
            client_command=["psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1"],
            env={"POSTGRES_PASSWORD": "mysecretpassword"},
            error_normalizer=self._normalize_error,
            init_queries=["CREATE TABLE IF NOT EXISTS x(x int)"],
            timeout=args.query_timeout,
            is_query_alive_callback=self._is_query_alive,
            crash_detector=self._crash_detector
        )

    def _is_query_alive(self, executor: DockerExecutor) -> bool:
        # Run a query to check if there are any active queries (excluding the check query itself if possible,
        # but pg_backend_pid() handles that for the current session).
        # We assume single threaded execution so any other active query is the "hanging" one.
        cmd = [
            "psql", "-U", "postgres", "-d", "postgres", "--csv", "-c",
            "SELECT COUNT(1) FROM pg_stat_activity WHERE state='active' and pid != pg_backend_pid()"
        ]
        stdout = executor.exec_cmd(cmd)
        # If stdout matches "count\n0", then count is 0 -> Not alive.
        # Otherwise -> Alive.
        return stdout.strip() != "count\n0"

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return "server closed the connection unexpectedly" in stderr

    def _normalize_error(self, stdout: str, stderr: str) -> str:
        if not stderr:
            return ""
        lines = stderr.splitlines(keepends=True)
        first_line = lines[0] if lines else ""
        
        # Replace text inside of the double-quotes with three dots
        return re.sub(r'"[^"]*"', '"..."', first_line)

    def create_query_generator(self, grammar_file: str, max_cycle_length: int):
        return QueryGenerator(
            grammar_file,
            max_cycle_length=max_cycle_length,
            grammar_token_rewriter=self._grammar_token_rewriter,
            removed_rules=self._get_removed_rules(),
            template_token_rewriter=self._template_token_rewriter
        )

    def _grammar_token_rewriter(self, token: str) -> str:
        replacements = {
            "EQUALS_GREATER": "=>",
            "LESS_EQUALS": "<=",
            "GREATER_EQUALS": ">=",
            "LESS_GREATER": "<>",
            "NOT_EQUALS": "!=",
            "TYPECAST": "::",
            "DOT_DOT": "..",
            "COLON_EQUALS": ":=",
            "NOT_LA": "NOT",
            "WITH_LA": "WITH",
        }
        if token in replacements:
            return replacements[token]
        
        if token.endswith("_P"):
            return token[:-2]
            
        return token

    def _get_removed_rules(self) -> List[str]:
        return ["ColId", "type_function_name", "ColLabel", "BareColLabel"]

    def _template_token_rewriter(self, token: str) -> str:
        replacements = {
            "ColId": "x x$",
            "type_function_name": "x",
            "ColLabel": "x$",
            "BareColLabel": "x$",
            "Sconst": '"1"',
            "Iconst": "0",
            "ICONST": "0",
            "FCONST": "0",
            "BCONST": 'b"0"',
            "XCONST": 'x"0"',
        }
        return replacements.get(token, token)
