import re
import subprocess
from typing import Optional, List, Dict
from .base import DatabaseModule, Executor
from .docker_db import DockerExecutor
from sqeeel.query_generator.generator import QueryGenerator

class TiDBExecutor(DockerExecutor):
    def start(self):
        super().start()
        # Install mysql client since it's missing in pingcap/tidb image
        # Rocky Linux uses dnf
        if not self._container_id:
            raise RuntimeError("Container ID is None after start()")
            
        try:
            print("Installing mysql client in TiDB container...")
            subprocess.check_call(
                ["docker", "exec", self._container_id, "dnf", "install", "-y", "mysql"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to install mysql client: {e}")

class TiDBModule(DatabaseModule):
    def __init__(self):
        self._token_map: Optional[Dict[str, str]] = None

    @property
    def name(self) -> str:
        return "tidb"

    def configure_args(self, parser):
        parser.add_argument(
            "--db-image",
            type=str,
            default="pingcap/tidb:latest",
            help="The Docker image to use for the database.",
        )

    def create_executor(self, args) -> Executor:
        return TiDBExecutor(
            image_name=args.db_image,
            container_name="sqeeel-test-db-tidb",
            # Connect to local TiDB
            client_command=["mysql", "-h", "127.0.0.1", "-P", "4000", "-u", "root", "-D", "test"],
            env={},
            error_normalizer=self._normalize_error,
            init_queries=["CREATE TABLE IF NOT EXISTS x(x int)"],
            timeout=args.query_timeout,
            is_query_alive_callback=self._is_query_alive,
            server_cancel_callback=self._server_cancel,
            crash_detector=self._crash_detector
        )

    def _send_ns_signal(self, nspid: int, signal: str = "SIGINT"):
        """
        Sends SIGINT to the main process inside the container.
        """
        subprocess.run(["docker", "exec", self.container_name, "bash", "-c", "kill -"+signal+" "+str(nspid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _is_query_alive(self, executor: DockerExecutor) -> Optional[str]:
        # Check for active queries in information_schema.processlist
        cmd = [
            "mysql", "-h", "127.0.0.1", "-P", "4000", "-u", "root", "-D", "test", "-N", "-s", "-e",
            "SELECT id FROM information_schema.processlist WHERE command != 'Sleep' AND id != CONNECTION_ID()"
        ]
        
        try:
            stdout = executor.exec_cmd(cmd)
            result = stdout.strip()
            return result if result else None
        except Exception:
            return None

    def _server_cancel(self, executor: DockerExecutor, query_id: str):
        cmd = [
            "mysql", "-h", "127.0.0.1", "-P", "4000", "-u", "root", "-D", "test", "-e",
            f"KILL QUERY {query_id}"
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
        
        first_line = re.sub(r"'[^']*'", "'...'", first_line)
        first_line = re.sub(r'near "[^"]*["]?', 'near "..."', first_line)
        first_line = re.sub(r'line \d+ column \d+', 'line X column X', first_line)
        return first_line.strip()

    def create_query_generator(self, grammar_file: str, max_cycle_length: int):
        # Load token map from grammar file
        self._load_token_map(grammar_file)
        
        return QueryGenerator(
            grammar_file,
            max_cycle_length=max_cycle_length,
            grammar_token_rewriter=self._grammar_token_rewriter,
            removed_rules=self._get_removed_rules(),
            template_token_rewriter=self._template_token_rewriter
        )

    def _load_token_map(self, grammar_file: str):
        if self._token_map is not None:
            return

        self._token_map = {}
        try:
            with open(grammar_file, 'r') as f:
                lines = f.readlines()
            
            in_token_section = False
            # Regex to match: name "value"
            token_regex = re.compile(r'^(\w+)\s+"([^"]+)"')
            
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                    
                if stripped.startswith("%token"):
                    in_token_section = True
                    continue
                
                if stripped.startswith("%") and not stripped.startswith("%token"):
                    in_token_section = False
                    continue
                
                if in_token_section:
                    # Ignore comments
                    if stripped.startswith("/*") or stripped.startswith("//"):
                        continue

                    m = token_regex.match(stripped)
                    if m:
                        name, val = m.groups()
                        if name not in {
                            "singleAtIdentifier", "doubleAtIdentifier", "hintComment",
                            "stringLit", "floatLit", "decLit", "intLit", "hexLit", "bitLit"
                        }:
                            self._token_map[name] = val

        except Exception as e:
            print(f"Warning: Failed to load token map from {grammar_file}: {e}")
        print(f"Loaded {len(self._token_map)} tokens for TiDB from grammar.")

    def _grammar_token_rewriter(self, token: str) -> str:
        if self._token_map and token in self._token_map:
            return self._token_map[token]
        
        # Fallbacks similar to MariaDB if not found in map
        replacements = {
            "AND_AND": "&&",
            "OR_OR": "||",
            "LE": "<=",
            "NE": "!=",
            "GE": ">=",
            "EQ": "=",
            # btFuncTokenMap from /pkg/parser/misc.go
            "builtinBitAnd": "BIT_AND",
            "builtinBitOr": "BIT_OR",
            "builtinBitXor": "BIT_XOR",
            "builtinCast": "CAST",
            "builtinCount": "COUNT",
            "builtinApproxCountDistinct": "APPROX_COUNT_DISTINCT",
            "builtinApproxPercentile": "APPROX_PERCENTILE",
            "builtinCurDate": "CURDATE",
            "builtinCurTime": "CURTIME",
            "builtinDateAdd": "DATE_ADD",
            "builtinDateSub": "DATE_SUB",
            "builtinExtract": "EXTRACT",
            "builtinGroupConcat": "GROUP_CONCAT",
            "builtinMax": "MAX",
            "builtinSubstring": "MID",
            "builtinMin": "MIN",
            "builtinNow": "NOW",
            "builtinPosition": "POSITION",
            #"builtinStddevPop": "STD",
            #"builtinStddevPop": "STDDEV",
            "builtinStddevPop": "STDDEV_POP",
            "builtinStddevSamp": "STDDEV_SAMP",
            "builtinSubstring": "SUBSTR",
            #"builtinSubstring": "SUBSTRING",
            "builtinSum": "SUM",
            "builtinSysDate": "SYSDATE",
            "builtinTranslate": "TRANSLATE",
            "builtinTrim": "TRIM",
            #"builtinVarPop": "VARIANCE",
            "builtinVarPop": "VAR_POP",
            "builtinVarSamp": "VAR_SAMP",                                                                               
        }
        if token in replacements:
            return replacements[token]
            
        return token

    def _get_removed_rules(self) -> List[str]:
        # Rules to exclude from generation
        return ["identifier"]

    def _template_token_rewriter(self, token: str) -> str:
        replacements = {
            "identifier": "x",
            "ident": "x",
            "stringLit": '""',
            "intType": "INT", # Ensure types are mapped if used as tokens
            "singleAtIdentifier": "@x",
            "doubleAtIdentifier": "@@x",
            "hintComment": "/*+ hint */",
            "floatLit": "0.0",
            "decLit": "0",
            "intLit": "0",
            "hexLit": "0x0",
            "bitLit": "b'0'",
        }
        
        # If the token is in our map (e.g. intType -> INT), use that mapping primarily?
        # No, template rewriter is for placeholders like 'identifier'.
        # But if the grammar used 'intType' in a rule and we want 'INT' in the output,
        # grammar_token_rewriter should handle it.
        # template_token_rewriter is for tokens that need specific values (like literals).
        
        return replacements.get(token, token)
