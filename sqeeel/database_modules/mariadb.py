import re
from typing import Optional, List
from .base import DatabaseModule, Executor
from .docker_db import DockerExecutor
from sqeeel.query_generator.generator import QueryGenerator

class MariaDBModule(DatabaseModule):
    @property
    def name(self) -> str:
        return "mariadb"

    def configure_args(self, parser):
        parser.add_argument(
            "--db-image",
            type=str,
            default="mariadb:latest",
            help="The Docker image to use for the database.",
        )

    def create_executor(self, args) -> Executor:
        return DockerExecutor(
            image_name=args.db_image,
            container_name="sqeeel-test-db-mariadb",
            client_command=["mariadb", "-u", "root", "-pmysecretpassword", "-D", "testdb", "-B", "--skip-print-query-on-error"],
            env={
                "MARIADB_ROOT_PASSWORD": "mysecretpassword",
                "MARIADB_DATABASE": "testdb"
            },
            error_normalizer=self._normalize_error,
            init_queries=["CREATE TABLE IF NOT EXISTS x(x int)"],
            timeout=args.query_timeout,
            is_query_alive_callback=self._is_query_alive,
            crash_detector=self._crash_detector
        )

    def _is_query_alive(self, executor: DockerExecutor) -> bool:
        # Check for active queries in information_schema.processlist
        # Excluding the current check query might be tricky if not careful, but usually
        # the check query is fast. We look for other queries.
        # Command must be non-interactive to output cleanly.
        cmd = [
            "mariadb", "-u", "root", "-pmysecretpassword", "-D", "testdb", "-e",
            "SELECT COUNT(1) FROM information_schema.processlist WHERE command != 'Sleep' AND id != CONNECTION_ID()"
        ]
        # mariadb output format with -e is tabular by default, we can parse it.
        # Or use -N (skip column names) -s (silent/raw)
        cmd = [
            "mariadb", "-u", "root", "-pmysecretpassword", "-D", "testdb", "-N", "-s", "-e",
            "SELECT COUNT(1) FROM information_schema.processlist WHERE command != 'Sleep' AND id != CONNECTION_ID()"
        ]
        
        try:
            stdout = executor.exec_cmd(cmd)
            # if 0 -> not alive
            return stdout.strip() != "0"
        except Exception:
            return False

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return "Lost connection to MySQL server" in stderr or "Can't connect to MySQL server" in stderr

    def _normalize_error(self, stdout: str, stderr: str) -> str:
        if not stderr:
            return stdout if stdout else ""
        lines = stderr.splitlines(keepends=True)
        first_line = lines[0] if lines else ""
        
        # Replace text inside of the single-quotes with three dots
        return re.sub(r"'[^']*'", "'...'", first_line)

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
            # $ cat grammars/mariadb12-lex.h | perl -ne 'print "\"$2\": \"$1\",\n" if(/^\s*{ "([^"]+)",\s*SYM[(]([^)]*?)(?:_SYM)?[)]},/ && $1 ne $2)'
            "AND_AND": "&&",
            "LE": "<=",
            "NE": "<>",
            "NE": "!=",
            "GE": ">=",
            "SHIFT_LEFT": "<<",
            "SHIFT_RIGHT": ">>",
            "EQUAL": "<=>",
            "ARROW": "=>",
            "AUTO_INC": "AUTO_INCREMENT",
            "BEGIN_MARIADB": "BEGIN",
            "BLOB_MARIADB": "BLOB",
            "BODY_MARIADB": "BODY",
            "CHAR": "CHARACTER",
            "CLOB_MARIADB": "CLOB",
            "CONTINUE_MARIADB": "CONTINUE",
            "CURDATE": "CURRENT_DATE",
            "CURTIME": "CURRENT_TIME",
            "NOW": "CURRENT_TIMESTAMP",
            "DECIMAL": "DEC",
            "DECLARE_MARIADB": "DECLARE",
            "DISTINCT": "DISTINCTROW",
            "ELSEIF_MARIADB": "ELSEIF",
            "ELSIF_MARIADB": "ELSIF",
            "EXCEPTION_MARIADB": "EXCEPTION",
            "EXIT_MARIADB": "EXIT",
            "DESCRIBE": "EXPLAIN",
            "COLUMNS": "FIELDS",
            "FLOAT": "FLOAT4",
            "DOUBLE": "FLOAT8",
            "GOTO_MARIADB": "GOTO",
            "TINYINT": "INT1",
            "SMALLINT": "INT2",
            "MEDIUMINT": "INT3",
            "INT": "INT4",
            "BIGINT": "INT8",
            "INT": "INTEGER",
            "RELAY_THREAD": "IO_THREAD",
            "CURTIME": "LOCALTIME",
            "MASTER_DEMOTE_TO_SLAVE": "MASTER_DEMOTE_TO_REPLICA",
            "MEDIUMINT": "MIDDLEINT",
            "MINUS_ORACLE": "MINUS",
            "NUMBER_MARIADB": "NUMBER",
            "OTHERS_MARIADB": "OTHERS",
            "PACKAGE_MARIADB": "PACKAGE",
            "RAISE_MARIADB": "RAISE",
            "RAW_MARIADB": "RAW",
            "SLAVE": "REPLICA",
            "SLAVES": "REPLICAS",
            "SLAVE_POS": "REPLICA_POS",
            "RETURN_MARIADB": "RETURN",
            "REGEXP": "RLIKE",
            "ROWTYPE_MARIADB": "ROWTYPE",
            "DATABASE": "SCHEMA",
            "DATABASES": "SCHEMAS",
            "ANY": "SOME",
            "SECOND": "SQL_TSI_SECOND",
            "MINUTE": "SQL_TSI_MINUTE",
            "HOUR": "SQL_TSI_HOUR",
            "DAY": "SQL_TSI_DAY",
            "WEEK": "SQL_TSI_WEEK",
            "MONTH": "SQL_TSI_MONTH",
            "QUARTER": "SQL_TSI_QUARTER",
            "YEAR": "SQL_TSI_YEAR",
            "TIMESTAMP_ADD": "TIMESTAMPADD",
            "TIMESTAMP_DIFF": "TIMESTAMPDIFF",
            "RESOURCES": "USER_RESOURCES",
            "VARCHAR": "VARCHARACTER",
            "VARCHAR2_MARIADB": "VARCHAR2",
            "DATE_ADD_INTERVAL": "DATE_ADD",
            "DATE_SUB_INTERVAL": "DATE_SUB",
            "SUBSTRING": "MID",
            "STD": "STDDEV",
            #"STD": "STDDEV_POP",
            "SUBSTRING": "SUBSTR",
            "USER": "SYSTEM_USER",
            "VARIANCE": "VAR_POP",
        }
        if token in replacements:
            return replacements[token]
        
        if token.endswith("_SYM"):
            return token[:-4]

        return token

    def _get_removed_rules(self) -> List[str]:
        # Rules to exclude from generation
        return ["ident", "table_ident", "opt_table_alias_clause"]

    def _template_token_rewriter(self, token: str) -> str:
        replacements = {
            "ident": "x",
            "table_ident": "x",
            "IDENT": "x",
            "NUM": "0",
            "opt_table_alias_clause": "x$",
        }
        return replacements.get(token, token)
