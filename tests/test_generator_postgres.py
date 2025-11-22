import unittest
import os
from sqeeel.query_generator.generator import QueryGenerator, QueryTemplate
from sqeeel.database_modules.postgresql import PostgresModule

class TestQueryGeneratorPostgres(unittest.TestCase):
    def setUp(self):
        self.pg_module = PostgresModule()

    def test_grammar_token_rewriter(self):
        # Test simple replacements
        self.assertEqual(self.pg_module._grammar_token_rewriter("EQUALS_GREATER"), "=>")
        self.assertEqual(self.pg_module._grammar_token_rewriter("LESS_EQUALS"), "<=")
        self.assertEqual(self.pg_module._grammar_token_rewriter("GREATER_EQUALS"), ">=")
        self.assertEqual(self.pg_module._grammar_token_rewriter("LESS_GREATER"), "<>")
        self.assertEqual(self.pg_module._grammar_token_rewriter("NOT_EQUALS"), "!=")
        self.assertEqual(self.pg_module._grammar_token_rewriter("TYPECAST"), "::")
        self.assertEqual(self.pg_module._grammar_token_rewriter("DOT_DOT"), "..")
        self.assertEqual(self.pg_module._grammar_token_rewriter("COLON_EQUALS"), ":=")
        
        # Test suffix removal
        self.assertEqual(self.pg_module._grammar_token_rewriter("IF_P"), "IF")
        self.assertEqual(self.pg_module._grammar_token_rewriter("ADD_P"), "ADD")
        
        # Test no change
        self.assertEqual(self.pg_module._grammar_token_rewriter("SELECT"), "SELECT")

    def test_template_token_rewriter(self):
        self.assertEqual(self.pg_module._template_token_rewriter("ColId"), "x x$")
        self.assertEqual(self.pg_module._template_token_rewriter("type_function_name"), "x")
        self.assertEqual(self.pg_module._template_token_rewriter("ColLabel"), "x$")
        self.assertEqual(self.pg_module._template_token_rewriter("BareColLabel"), "x$")
        self.assertEqual(self.pg_module._template_token_rewriter("Sconst"), '"1"')
        self.assertEqual(self.pg_module._template_token_rewriter("Iconst"), "0")
        self.assertEqual(self.pg_module._template_token_rewriter("FCONST"), "0")
        self.assertEqual(self.pg_module._template_token_rewriter("BCONST"), 'b"0"')
        self.assertEqual(self.pg_module._template_token_rewriter("XCONST"), 'x"0"')
        
        # Test no change
        self.assertEqual(self.pg_module._template_token_rewriter("SELECT"), "SELECT")

    def test_integration_with_generator(self):
        # Create a dummy grammar file for testing with a cycle to trigger template generation
        grammar_content = """
        %%
        stmt : item recursive
             | other recursive
             ;
        
        recursive : stmt 
                  | END
                  ;
        
        item : SELECT Iconst ;
        other : CHECK EQUALS_GREATER Sconst ;
        
        REMOVE_ME : 'foo' ;
        """
        
        with open('tests/temp_pg_grammar.y', 'w') as f:
            f.write(grammar_content)
            
        generator = self.pg_module.create_query_generator('tests/temp_pg_grammar.y', max_cycle_length=5)
        
        # Iconst -> 0
        # Sconst -> "1"
        # EQUALS_GREATER -> =>
        # END -> END (not rewritten)
        # SELECT -> SELECT
        # CHECK -> CHECK
        
        # stmt -> item recursive -> SELECT Iconst recursive -> SELECT 0 recursive
        # recursive -> stmt -> item recursive -> SELECT 0 recursive
        
        # Cycle: stmt -> recursive -> stmt
        # Path: stmt
        
        templates = generator.generate_templates('stmt')
        
        generated_strs = set()
        for t in templates:
            # Reconstruct full string
            s = f"{t.prefix}{t.left}{t.middle}{t.right}{t.suffix}".strip()
            # Collapse multiple spaces
            s = " ".join(s.split())
            generated_strs.add(s)
        
        # We should see expanded tokens in the generated templates
        
        # Cycle expansion involves SELECT 0 ... 
        found_select = any('SELECT 0' in s for s in generated_strs)
        self.assertTrue(found_select, f"Expected 'SELECT 0' in templates, got: {generated_strs}")
        
        found_check = any('CHECK => "1"' in s for s in generated_strs)
        self.assertTrue(found_check, f"Expected 'CHECK => \"1\"' in templates, got: {generated_strs}")

        if os.path.exists('tests/temp_pg_grammar.y'):
            os.remove('tests/temp_pg_grammar.y')

if __name__ == '__main__':
    unittest.main()