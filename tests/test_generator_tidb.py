import unittest
import os
import sys

# Add workspace to path
sys.path.append(os.getcwd())

from sqeeel.database_modules.tidb import TiDBModule

class TestQueryGeneratorTiDB(unittest.TestCase):
    def setUp(self):
        self.tidb_module = TiDBModule()

    def test_load_token_map(self):
        # Create a dummy grammar file
        grammar_content = """
        %token <ident>
            intType "INT"
            varcharType "VARCHAR"
            andand "&&"
        """
        filename = 'tests/temp_tidb_grammar_tokens.y'
        with open(filename, 'w') as f:
            f.write(grammar_content)
            
        try:
            self.tidb_module._load_token_map(filename)
            self.assertEqual(self.tidb_module._token_map.get('intType'), 'INT')
            self.assertEqual(self.tidb_module._token_map.get('varcharType'), 'VARCHAR')
            self.assertEqual(self.tidb_module._token_map.get('andand'), '&&')
        finally:
            if os.path.exists(filename):
                os.remove(filename)

    def test_grammar_token_rewriter(self):
        # Preload map
        self.tidb_module._token_map = {
            "intType": "INT",
            "andand": "&&"
        }
        
        self.assertEqual(self.tidb_module._grammar_token_rewriter("intType"), "INT")
        self.assertEqual(self.tidb_module._grammar_token_rewriter("andand"), "&&")
        
        # Test fallback
        self.assertEqual(self.tidb_module._grammar_token_rewriter("AND_AND"), "&&")
        self.assertEqual(self.tidb_module._grammar_token_rewriter("OR_OR"), "||")
        self.assertEqual(self.tidb_module._grammar_token_rewriter("LE"), "<=")

    def test_template_token_rewriter(self):
        self.assertEqual(self.tidb_module._template_token_rewriter("identifier"), "x")
        self.assertEqual(self.tidb_module._template_token_rewriter("ident"), "x")
        self.assertEqual(self.tidb_module._template_token_rewriter("stringLit"), "'x'")
        self.assertEqual(self.tidb_module._template_token_rewriter("intType"), "INT")

    def test_integration_with_generator(self):
        # Create a dummy grammar file for testing
        grammar_content = """
        %token <ident>
           intType "INT"
           select "SELECT"
        
        %%
        stmt : item recursive
             ;
        
        recursive : stmt 
                  | /* empty */
                  ;
        
        item : select intType identifier ;
        """
        
        filename = 'tests/temp_tidb_grammar.y'
        with open(filename, 'w') as f:
            f.write(grammar_content)
            
        try:
            generator = self.tidb_module.create_query_generator(filename, max_cycle_length=5)
            
            # item -> select intType identifier -> SELECT INT x
            
            # Since identifier is removed in _get_removed_rules, it should NOT appear in grammar templates?
            # Wait, removed_rules removes RULES. 'identifier' is a TOKEN here (or rule if defined).
            # If 'identifier' is a token, removing it from rules does nothing if it's not a rule.
            # But usually 'identifier' is a terminal token.
            # In TiDB grammar it is a token.
            
            # However, if I remove a rule, the generator won't traverse it.
            # If 'identifier' is just a token, it will be kept.
            
            templates = generator.generate_templates('stmt')
            
            generated_strs = set()
            for t in templates:
                s = f"{t.prefix}{t.left}{t.middle}{t.right}{t.suffix}".strip()
                s = " ".join(s.split())
                generated_strs.add(s)
            
            # We expect SELECT INT x
            # Note: recursive allows empty, so stmt -> item -> SELECT INT x
            
            # Check for SELECT INT x
            # intType -> INT (grammar rewriter via map)
            # select -> SELECT (grammar rewriter via map)
            # identifier -> x (template rewriter)
            
            found = any('SELECT INT x' in s for s in generated_strs)
            self.assertTrue(found, f"Expected 'SELECT INT x' in templates, got: {generated_strs}")
            
        finally:
            if os.path.exists(filename):
                os.remove(filename)

if __name__ == '__main__':
    unittest.main()
