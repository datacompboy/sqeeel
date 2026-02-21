import re
from typing import Optional, List, Dict
from .base import DatabaseModule, Executor
from .docker_db import DockerExecutor
from sqeeel.query_generator.generator import QueryGenerator

class MySQLModule(DatabaseModule):
    @property
    def name(self) -> str:
        return "mysql"

    def configure_args(self, parser):
        parser.add_argument(
            "--db-image",
            type=str,
            default="mysql:latest",
            help="The Docker image to use for the database.",
        )

    def create_executor(self, args) -> Executor:
        return DockerExecutor(
            image_name=args.db_image,
            container_name="sqeeel-test-db-mysql",
            client_command=["bash", "-c", "MYSQL_PWD=mysecretpassword mysql -u root -D testdb -B --skip-column-names"],
            env={
                "MYSQL_ROOT_PASSWORD": "mysecretpassword",
                "MYSQL_DATABASE": "testdb",
            },
            error_normalizer=self._normalize_error,
            init_queries=["CREATE TABLE IF NOT EXISTS x(x int)"],
            timeout=args.query_timeout,
            is_query_alive_callback=self._is_query_alive,
            server_cancel_callback=self._server_cancel,
            crash_detector=self._crash_detector
        )

    def _is_query_alive(self, executor: DockerExecutor) -> Optional[str]:
        # Check for active queries in information_schema.processlist
        cmd = [
            "bash", "-c", "MYSQL_PWD=mysecretpassword mysql -u root -D testdb -N -s -e 'SELECT id FROM information_schema.processlist WHERE command != \"Sleep\" AND id != CONNECTION_ID()'"
        ]
        
        stdout = executor.exec_cmd(cmd)
        result = stdout.strip()
        return result if result else None

    def _server_cancel(self, executor: DockerExecutor, query_id: str):
        cmd = [
            "bash", "-c", f"MYSQL_PWD=mysecretpassword mysql -u root -D testdb -e 'KILL QUERY {query_id}'"
        ]
        try:
            executor.exec_cmd(cmd)
        except Exception:
            pass

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return "Lost connection to MySQL server" in stderr or "Can't connect to MySQL server" in stderr

    def _normalize_error(self, stdout: str, stderr: str) -> str:
        if not stderr:
            return stdout if stdout else ""
        lines = stderr.splitlines(keepends=True)
        first_line = lines[0] if lines else ""

        first_line = re.sub(r"\d+ bytes ", "X bytes ", first_line)

        # Replace text inside of the single-quotes with three dots
        return re.sub(r"'[^']*'", "'...'", first_line)

    def create_query_generator(self, grammar_file: str, max_cycle_length: int):
        return QueryGenerator(
            grammar_file,
            max_cycle_length=max_cycle_length,
            grammar_token_rewriter=self._grammar_token_rewriter,
            removed_rules=self._get_removed_rules(),
            template_token_rewriter=self._template_token_rewriter,
            rules_mutator=self._rules_mutator
        )

    def _rules_mutator(self, rules: Dict[str, List[List[str]]]):
        rules["opt_from_clause"] = [["from_clause"]]
        rules["from_tables"] = [["table_reference_list"]]

    def _grammar_token_rewriter(self, token: str) -> str:
        replacements = {
            # sql/gen_lex_token.cc
            "WITH_ROLLUP_SYM": "WITH ROLLUP",
            "NOT2_SYM": "!",
            "OR2_SYM": "||",
            #"PARAM_MARKER": "?",
            "SET_VAR": ":=",
            "UNDERSCORE_CHARSET": "(_charset)",
            "END_OF_INPUT": "",
            "JSON_SEPARATOR_SYM": "->",
            "JSON_UNQUOTED_SEPARATOR_SYM": "->>",
            # $ cat grammars/mysql-lex.h | perl -ne 'print "\"$2\": \"$1\",\n" if(/^\s*{SYM(?:_.*?)?\("([^"]+)",\s* ([^)]*?)(?:_SYM|_HINT)?[)]},/ && $1 ne $2)'
            "AND_AND": "&&",
            "LT": "<",
            "LE": "<=",
            # "NE": "<>",
            "NE": "!=",
            "EQ": "=",
            "GT": ">",
            "GE": ">=",
            "SHIFT_LEFT": "<<",
            "SHIFT_RIGHT": ">>",
            "EQUAL": "<=>",
            "AUTO_INC": "AUTO_INCREMENT",
            "CHAR": "CHARACTER",
            "CURDATE": "CURRENT_DATE",
            "CURTIME": "CURRENT_TIME",
            "NOW": "CURRENT_TIMESTAMP",
            "DECIMAL": "DEC",
            "DISTINCT": "DISTINCTROW",
            "DESCRIBE": "EXPLAIN",
            "COLUMNS": "FIELDS",
            "FLOAT": "FLOAT4",
            "DOUBLE": "FLOAT8",
            "GEOMETRYCOLLECTION": "GEOMCOLLECTION",
            "TINYINT": "INT1",
            "SMALLINT": "INT2",
            "MEDIUMINT": "INT3",
            "INT": "INT4",
            "BIGINT": "INT8",
            "INT": "INTEGER",
            "RELAY_THREAD": "IO_THREAD",
            "NOW": "LOCALTIME",
            # "NOW": "LOCALTIMESTAMP",
            "MAX_VALUE": "MAXVALUE",
            "MEDIUMINT": "MIDDLEINT",
            "NDBCLUSTER": "NDB",
            "REGEXP": "RLIKE",
            "DATABASE": "SCHEMA",
            "DATABASES": "SCHEMAS",
            "ANY": "SOME",
            "SOURCE_COMPRESSION_ALGORITHM": "SOURCE_COMPRESSION_ALGORITHMS",
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
            "TINYTEXT_SYN": "TINYTEXT",
            "RESOURCES": "USER_RESOURCES",
            "VARCHAR": "VARCHARACTER",
            "OR_OR": "||",
            "DATE_ADD_INTERVAL": "DATE_ADD",
            "DATE_SUB_INTERVAL": "DATE_SUB",
            "SUBSTRING": "MID",
            "USER": "SESSION_USER",
            "STD": "STDDEV",
            #"STD": "STDDEV_POP",
            #"SUBSTRING": "SUBSTR",
            #"USER": "SYSTEM_USER",
            "VARIANCE": "VAR_POP",
            "DERIVED_MERGE": "MERGE",
            "NO_DERIVED_MERGE": "NO_MERGE",
        }
        if token in replacements:
            return replacements[token]
        
        if token.endswith("_SYM"):
            return token[:-4]

        if token.endswith("_HINT"):
            return token[:-5]

        return token

    def _get_removed_rules(self) -> List[str]:
        # Rules to exclude from generation
        return ["ident", "table_ident", "opt_table_alias", "into_destination"]

    def _template_token_rewriter(self, token: str) -> str:
        replacements = {
            # sql/gen_lex_token.cc
            "BIN_NUM": "0b00",
            "DECIMAL_NUM": "0",
            "FLOAT_NUM": "0",
            "HEX_NUM": "0x00",
            "LEX_HOSTNAME": "hostname",
            "LONG_NUM": "0",
            "NUM": "0",
            "TEXT_STRING": "'x'",
            "NCHAR_STRING": "N'x'",
            "ULONGLONG_NUM": "0",
            "IDENT": "x",
            "IDENT_QUOTED": "`x`",
            # shorteners
            "into_destination": "@x",
            "table_ident": "x",
            "ident": "x",
            "ident_or_text": "x",
            "opt_table_alias": "x$",
        }
        return replacements.get(token, token)
