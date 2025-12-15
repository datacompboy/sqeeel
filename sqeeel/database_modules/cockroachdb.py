import subprocess
import time
import uuid
import re
from typing import List, Optional
from .base import DatabaseModule, Executor, ExecutionStatus
from .docker_db import DockerExecutor, DockerExecResult
from sqeeel.query_generator.generator import QueryGenerator

class CockroachExecutor(DockerExecutor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.network_name = f"sqeeel-net-{uuid.uuid4().hex[:8]}"
        self.node_names = [f"{self.container_name}-{i}" for i in range(1, 4)]
        self.container_ids = []
        # We need to set container_name to a real container name for DockerExecutor methods
        # like _client_cancel that rely on it.
        self.container_name = self.node_names[0]

    def start(self):
        # Create network
        subprocess.check_call(["docker", "network", "create", "-d", "bridge", self.network_name])
        
        try:
            # Start nodes
            join_args = ",".join(self.node_names)
            for name in self.node_names:
                cmd = [
                    "docker", "run", "-d", 
                    "--name", name, 
                    "--hostname", name, 
                    "--net", self.network_name,
                    self.image_name, 
                    "start", "--insecure", f"--join={join_args}",
                    "--log={capture-stray-errors: {enable: false}}",  # Capture stack crashes to stderr
                    "--max-sql-memory=1G",  # Reduce memory limit for testing
                    "--max-go-memory=4G", # Reduce memory limit for testing
                ]
                cid = subprocess.check_output(cmd).decode("utf-8").strip()
                self.container_ids.append(cid)

            # Init cluster
            print("Waiting for nodes to start...")
            time.sleep(5) # Give them a moment to start up
            
            # Run init on first node
            print("Initializing cluster...")
            init_cmd = ["docker", "exec", self.container_ids[0], "./cockroach", "init", "--insecure"]
            subprocess.check_call(init_cmd)
            
            # Set the primary container ID for the base class to use
            self._container_id = self.container_ids[0]
            
        except Exception as e:
            print(f"Failed to start CockroachDB cluster: {e}")
            self.stop()
            raise

    def stop(self):
        for cid in self.container_ids:
            subprocess.run(["docker", "stop", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "rm", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.container_ids = []
        self._container_id = None
        
        subprocess.run(["docker", "network", "rm", self.network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_for_ready(self):
        print("Waiting for database to be ready...")
        start_time = time.time()
        last_error = None
        while True:
            try:
                result = self.run_query(self.test_query)
                if result.exit_code == 0:
                    break
                else:
                    last_error = f"Exit code {result.exit_code}: {result.stderr or result.stdout}"
            except Exception as e:
                last_error = str(e)
            
            if time.time() - start_time > 60:
                print(f"DEBUG: Last error during wait_for_ready: {last_error}")
                raise TimeoutError(f"Database failed to start within 60 seconds. Last error: {last_error}")
            
            time.sleep(1)
            
        print("Database is ready. Running initialization queries...")
        for query in self.init_queries:
            res = self.run_query(query)
            if res.exit_code != 0:
                raise RuntimeError(f"Initialization query failed: {query}\nError: {res.error_message}")

    def _is_container_running(self) -> bool:
        # Check if ALL containers are running
        if not self.container_ids:
            return False
            
        for name in self.node_names:
            try:
                cmd = ["docker", "inspect", "-f", "{{.State.Running}}", name]
                out = subprocess.check_output(cmd, text=True).strip()
                if out != "true":
                    return False
            except subprocess.CalledProcessError:
                return False
        return True

    def _send_ns_signal(self, nspid: int, signal: str = "SIGINT"):
        """
        Sends SIGINT to the main process inside the container.
        """
        subprocess.run(["docker", "exec", self.container_name, "bash", "-c", "kill -"+signal+" "+str(nspid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run_query(self, query: str) -> DockerExecResult:
        # CockroachDB sql client needs a semicolon to execute the query
        if not query.strip().endswith(";"):
            query += ";"
        return super().run_query(query)


class CockroachModule(DatabaseModule):
    @property
    def name(self) -> str:
        return "cockroachdb"

    def configure_args(self, parser):
        parser.add_argument(
            "--db-image",
            type=str,
            default="cockroachdb/cockroach:latest",
            help="The Docker image to use for the database.",
        )

    def create_executor(self, args) -> Executor:
        return CockroachExecutor(
            image_name=args.db_image,
            container_name="sqeeel-test-db-cockroach",
            # CockroachDB client is 'cockroach sql' or we can use psql. 
            # It's PG wire compatible, so psql might be easier if installed in image?
            # The image has 'cockroach sql' built-in.
            # Using './cockroach sql' inside the container.
            client_command=["./cockroach", "sql", "--insecure", "--database=defaultdb"],
            env={}, # No password for insecure mode
            error_normalizer=self._normalize_error,
            init_queries=["CREATE TABLE IF NOT EXISTS x(x int)"],
            timeout=args.query_timeout,
            # Reuse PG checks? Cockroach has similar system tables.
            is_query_alive_callback=self._is_query_alive,
            server_cancel_callback=self._server_cancel,
            crash_detector=self._crash_detector
        )

    def _is_query_alive(self, executor: DockerExecutor) -> Optional[str]:
        cmd = [
            "./cockroach", "sql", "--insecure", "--format=csv", "-e",
            "SELECT query_id FROM [SHOW QUERIES] WHERE session_id != (SELECT session_id FROM [show session_id])"
        ]
        
        try:
            stdout = executor.exec_cmd(cmd)
            lines = stdout.strip().splitlines()
            if len(lines) > 1: # Header + data
                return lines[1].strip() # Return first query ID found
        except Exception:
            pass
        return None

    def _server_cancel(self, executor: DockerExecutor, query_id: str):
        cmd = [
            "./cockroach", "sql", "--insecure", "-e",
            f"CANCEL QUERY '{query_id}'"
        ]
        try:
            executor.exec_cmd(cmd)
        except Exception:
            pass

    def _crash_detector(self, stdout: str, stderr: str) -> bool:
        return "connection lost" in stderr or "connection reset" in stderr or "failed to connect" in stderr

    def _normalize_error(self, stdout: str, stderr: str) -> str:
        if not stderr:
            if stdout.startswith("Error:"):
                 return stdout.splitlines()[0]
            return ""
        
        lines = stderr.splitlines(keepends=True)
        first_line = lines[0] if lines else ""
        
        first_line = re.sub(r"message size .*? bigger", "message size ... bigger", first_line)
        if len(first_line) > 200 and first_line.startswith("ERROR: "):
            first_line = first_line[:200] + "..."
        
        return re.sub(r'"[^"]*"', '"..."', first_line)

    def create_query_generator(self, grammar_file: str, max_cycle_length: int):
        # If grammar_file is not provided or is default, switch to cockroachdb-sql.y
        if not grammar_file:
             # This logic should be in main probably, but here we can hint/default?
             # args.grammar_file is passed. 
             pass

        return QueryGenerator(
            grammar_file,
            max_cycle_length=max_cycle_length,
            grammar_token_rewriter=self._grammar_token_rewriter,
            removed_rules=self._get_removed_rules(),
            template_token_rewriter=self._template_token_rewriter
        )

    # Reuse Postgres rewriters for now as requested
    def _grammar_token_rewriter(self, token: str) -> str:
        replacements = {
            # /pkg/sql/scanner/scan.go#func_Scan
            "DOT_DOT": "..",
            "NOT_EQUALS": "!=",
            "NOT_REGIMATCH": "!~*",
            "NOT": "!",
            "NOT_REGMATCH": "!~",
            "HELPTOKEN": "??",
            "JSON_SOME_EXISTS": "?|",
            "JSON_ALL_EXISTS": "?&",
            "FIRST_CONTAINS": "?@>",
            "FIRST_CONTAINED_BY": "?<@",
            "INET_CONTAINED_BY_OR_EQUALS": "<<=",
            "LSHIFT": "<<",
            "NOT_EQUALS": "<>",
            "COS_DISTANCE": "<=>",
            "LESS_EQUALS": "<=",
            "CONTAINED_BY": "<@",
            "DISTANCe": "<->",
            "NEG_INNER_PRODUCT": "<#>",
            "INET_CONTAINS_OR_EQUALS": ">>=",
            "RSHIFT": ">>",
            "GREATER_EQUALS": ">=",
            "TYPEANNOTATE": ":::",
            "TYPECAST": "::",
            "CBRT": "||/",
            "CONCAT": "||",
            "SQRT": "|/",
            "FLOOR_DIV": "//",
            "REGIMATCH": "~*",
            "ILIKE": "~~*",
            "LIKE": "~~",
            "CONTAINS": "@>",
            "AT_AT": "@@",
            "AND_AND": "&&",
            "FETCHTEXT": "->>",
            "FETCHVAL": "->",
            "FETCHTEXT_PATH": "#>>",
            "FETCHVAL_PATH": "#>",
            "REMOVE_PATH": "#-",
            # /pkg/sql/parser/lexer.go#func_Lex
            "INDEX_AFTER_ORDER_BY_BEFORE_AT": "INDEX",
            "INDEX_BEFORE_NAME_THEN_PAREN": "INDEX",
            "INDEX_BEFORE_PAREN": "INDEX",
            "GENERATED_ALWAYS": "GENERATED",
            "GENERATED_BY_DEFAULT": "GENERATED",
            "CREATE_CHANGEFEED_FOR_DATABASE": "CREATE",
            "SET_TRACING": "SET",
            "FOR_TABLE": "FOR",
            "FOR_JOB": "FOR",
        }
        if token in replacements:
            return replacements[token]
        
        if token.endswith("_LA"):
            return token[:-3]

        if token.endswith("_ALL"):
            return token[:-4]

        return token

    def _get_removed_rules(self) -> List[str]:
        return ["type_function_name", "name", "unreserved_keyword", "type_func_name_keyword", "type_func_name_no_crdb_extra_keyword", "col_name_keyword"]

    def _template_token_rewriter(self, token: str) -> str:
        replacements = {
            "Sconst": '"1"',
            "Iconst": "0",
            "ICONST": "0",
            "FCONST": "0",
            "BCONST": 'b"0"',
            "XCONST": 'x"0"',
            "IDENT": "x",
            "type_function_name": "x",
            "table_alias_name": "x$",
            "table_name": "x",
            "name": "x$",
        }
        return replacements.get(token, token)
