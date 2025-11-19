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
        )

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
            "equals_greater": "=>",
            "less_equals": "<=",
            "greater_equals": ">=",
            "less_greater": "<>",
            "not_equals": "!=",
            "typecast": "::",
            "dot_dot": "..",
            "colon_equals": ":=",
            "NOT_LA": "NOT",
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
            "FCONST": "0",
            "BCONST": 'b"0"',
            "XCONST": 'x"0"',
        }
        return replacements.get(token, token)
