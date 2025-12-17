import unittest
import os
import sys

# Add workspace to path
sys.path.append(os.getcwd())

from sqeeel.database_modules.tidb import TiDBModule

class TestQueryGeneratorTiDB(unittest.TestCase):
    def setUp(self):
        self.tidb_module = TiDBModule()

    def test_load_token_map_sections(self):
        # Test case with multiple %token sections and %type interleaved
        grammar_content = """
        %token <ident>
            token1 "T1"
            token2 "T2"

        %token <ident>
            token3 "T3"

        %type <statement>
            Type1 "Description 1"

        %token <ident>
            token4 "T4"
            
        %left
            token5 "T5"
        """
        filename = 'tests/temp_tidb_grammar_sections.y'
        with open(filename, 'w') as f:
            f.write(grammar_content)
            
        try:
            self.tidb_module._load_token_map(filename)
            self.assertEqual(self.tidb_module._token_map.get('token1'), 'T1')
            self.assertEqual(self.tidb_module._token_map.get('token2'), 'T2')
            self.assertEqual(self.tidb_module._token_map.get('token3'), 'T3')
            self.assertEqual(self.tidb_module._token_map.get('token4'), 'T4')
            
            # Type1 should not be in map
            self.assertIsNone(self.tidb_module._token_map.get('Type1'))
            
            # token5 is under %left, should not be in map (assuming logic only parses %token)
            self.assertIsNone(self.tidb_module._token_map.get('token5'))
            
        finally:
            if os.path.exists(filename):
                os.remove(filename)

    def test_special_tokens_handling(self):
        # Check that special tokens are removed from map and handled in template rewriter
        grammar_content = """
        %token <ident>
            singleAtIdentifier "identifier with single leading at"
            doubleAtIdentifier "identifier with double leading at"
            stringLit "string literal"
            intLit "int literal"
        """
        filename = 'tests/temp_tidb_grammar_special.y'
        with open(filename, 'w') as f:
            f.write(grammar_content)
            
        try:
            self.tidb_module._load_token_map(filename)
            
            # Should NOT be in map
            self.assertIsNone(self.tidb_module._token_map.get('singleAtIdentifier'))
            self.assertIsNone(self.tidb_module._token_map.get('doubleAtIdentifier'))
            self.assertIsNone(self.tidb_module._token_map.get('stringLit'))
            self.assertIsNone(self.tidb_module._token_map.get('intLit'))
            
            # Should be handled by template rewriter
            self.assertEqual(self.tidb_module._template_token_rewriter("singleAtIdentifier"), "@x")
            self.assertEqual(self.tidb_module._template_token_rewriter("doubleAtIdentifier"), "@@x")
            self.assertEqual(self.tidb_module._template_token_rewriter("stringLit"), '""')
            self.assertEqual(self.tidb_module._template_token_rewriter("intLit"), "0")
            
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
        self.assertEqual(self.tidb_module._template_token_rewriter("stringLit"), '""')
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
            
            templates = generator.generate_templates('stmt')
            
            generated_strs = set()
            for t in templates:
                s = f"{t.prefix}{t.left}{t.middle}{t.right}{t.suffix}".strip()
                s = " ".join(s.split())
                generated_strs.add(s)
            
            found = any('SELECT INT x' in s for s in generated_strs)
            self.assertTrue(found, f"Expected 'SELECT INT x' in templates, got: {generated_strs}")
            
        finally:
            if os.path.exists(filename):
                os.remove(filename)

if __name__ == '__main__':
    unittest.main()
