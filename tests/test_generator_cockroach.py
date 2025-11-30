import unittest
import os
from sqeeel.query_generator.generator import QueryGenerator
from sqeeel.database_modules.cockroachdb import CockroachModule

class TestQueryGeneratorCockroach(unittest.TestCase):
    def setUp(self):
        self.cr_module = CockroachModule()

    def test_grammar_token_rewriter(self):
        # Test replacements
        self.assertEqual(self.cr_module._grammar_token_rewriter("DOT_DOT"), "..")
        self.assertEqual(self.cr_module._grammar_token_rewriter("NOT"), "!")
        self.assertEqual(self.cr_module._grammar_token_rewriter("CONTAINS"), "@>")
        
        # Test NOT_EQUALS - checks which definition won (last one wins in Python dicts usually)
        # Line 200: "NOT_EQUALS": "<>" overwrites Line 189: "NOT_EQUALS": "!="
        self.assertEqual(self.cr_module._grammar_token_rewriter("NOT_EQUALS"), "<>")
        
        # Test suffix removal
        self.assertEqual(self.cr_module._grammar_token_rewriter("WITH_LA"), "WITH")
        self.assertEqual(self.cr_module._grammar_token_rewriter("UNION_ALL"), "UNION")
        
        # Test _P suffix is NOT handled (should remain as is)
        self.assertEqual(self.cr_module._grammar_token_rewriter("IF_P"), "IF_P")
        
        # Test no change
        self.assertEqual(self.cr_module._grammar_token_rewriter("SELECT"), "SELECT")

    def test_template_token_rewriter(self):
        self.assertEqual(self.cr_module._template_token_rewriter("Iconst"), "0")
        self.assertEqual(self.cr_module._template_token_rewriter("IDENT"), "x")
        self.assertEqual(self.cr_module._template_token_rewriter("table_name"), "x")
        
        # Test no change
        self.assertEqual(self.cr_module._template_token_rewriter("SELECT"), "SELECT")

    def test_integration_with_generator(self):
        # Create a dummy grammar file for testing
        grammar_content = """
        %%
        stmt : item recursive
             | other recursive
             ;
        
        recursive : stmt 
                  | END
                  ;
        
        item : SELECT Iconst ;
        other : CHECK CONTAINS Sconst ;
        
        REMOVE_ME : 'foo' ;
        """
        
        with open('tests/temp_cr_grammar.y', 'w') as f:
            f.write(grammar_content)
            
        generator = self.cr_module.create_query_generator('tests/temp_cr_grammar.y', max_cycle_length=5)
        
        templates = generator.generate_templates('stmt')
        
        generated_strs = set()
        for t in templates:
            # Reconstruct full string
            s = f"{t.prefix}{t.left}{t.middle}{t.right}{t.suffix}".strip()
            # Collapse multiple spaces
            s = " ".join(s.split())
            generated_strs.add(s)
        
        # Cycle expansion involves SELECT 0 ... 
        found_select = any('SELECT 0' in s for s in generated_strs)
        self.assertTrue(found_select, f"Expected 'SELECT 0' in templates, got: {generated_strs}")
        
        # CONTAINS -> @>
        # Sconst -> "1"
        found_check = any('CHECK @> "1"' in s for s in generated_strs)
        self.assertTrue(found_check, f"Expected 'CHECK @> \"1\"' in templates, got: {generated_strs}")

        if os.path.exists('tests/temp_cr_grammar.y'):
            os.remove('tests/temp_cr_grammar.y')

if __name__ == '__main__':
    unittest.main()
