import unittest
import tempfile
import os
from sqeeel.query_generator.antlr_parser import parse_antlr_grammar

class TestAntlrParser(unittest.TestCase):
    def setUp(self):
        self.test_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.g')
        self.file_path = self.test_file.name

    def tearDown(self):
        os.unlink(self.file_path)

    def write_grammar(self, content):
        with open(self.file_path, 'w') as f:
            f.write(content)

    def test_basic_rule(self):
        grammar = """
        grammar Test;
        rule : A B | C;
        """
        self.write_grammar(grammar)
        rules = parse_antlr_grammar(self.file_path)
        self.assertIn('rule', rules)
        self.assertEqual(rules['rule'], [['A', 'B'], ['C']])

    def test_skip_lexer_rules(self):
        grammar = """
        rule : TOKEN;
        TOKEN : 'token';
        fragment FRAG : 'frag';
        """
        self.write_grammar(grammar)
        rules = parse_antlr_grammar(self.file_path)
        self.assertIn('rule', rules)
        self.assertNotIn('TOKEN', rules)
        self.assertNotIn('FRAG', rules)
        self.assertEqual(rules['rule'], [['TOKEN']])

    def test_ignore_annotations(self):
        grammar = """
        rule [int x] returns [int y] locals [int z]
            @init { int i = 0; }
            : A { action } B
            ;
        """
        self.write_grammar(grammar)
        rules = parse_antlr_grammar(self.file_path)
        self.assertIn('rule', rules)
        self.assertEqual(rules['rule'], [['A', 'B']])

    def test_labels(self):
        grammar = """
        rule : l=A B | label+=C;
        """
        self.write_grammar(grammar)
        rules = parse_antlr_grammar(self.file_path)
        self.assertIn('rule', rules)
        self.assertEqual(rules['rule'], [['A', 'B'], ['C']])

    def test_synthetic_rules_parens(self):
        grammar = """
        rule : A (B | C) D;
        """
        self.write_grammar(grammar)
        rules = parse_antlr_grammar(self.file_path)
        self.assertIn('rule', rules)
        # rule -> [['A', '__synthetic_1', 'D']]
        # __synthetic_1 -> [['B'], ['C']]
        
        self.assertEqual(len(rules['rule']), 1)
        alt = rules['rule'][0]
        self.assertEqual(alt[0], 'A')
        self.assertEqual(alt[2], 'D')
        syn_name = alt[1]
        self.assertTrue(syn_name.startswith('__synthetic_'))
        
        self.assertIn(syn_name, rules)
        self.assertEqual(rules[syn_name], [['B'], ['C']])

    def test_quantifiers(self):
        grammar = """
        rule : A? B* C+;
        """
        self.write_grammar(grammar)
        rules = parse_antlr_grammar(self.file_path)
        self.assertIn('rule', rules)
        
        alt = rules['rule'][0]
        self.assertEqual(len(alt), 3)
        
        syn_a = alt[0]
        syn_b = alt[1]
        syn_c = alt[2]
        
        # Check A? -> A | []
        self.assertIn(syn_a, rules)
        self.assertIn(['A'], rules[syn_a])
        self.assertIn([], rules[syn_a])
        
        # Check B* -> B syn_b | []
        self.assertIn(syn_b, rules)
        self.assertIn(['B', syn_b], rules[syn_b])
        self.assertIn([], rules[syn_b])
        
        # Check C+ -> C syn_c | C
        self.assertIn(syn_c, rules)
        self.assertIn(['C', syn_c], rules[syn_c])
        self.assertIn(['C'], rules[syn_c])

    def test_comments(self):
        grammar = """
        // Line comment
        rule : A; /* Block comment */
        """
        self.write_grammar(grammar)
        rules = parse_antlr_grammar(self.file_path)
        self.assertIn('rule', rules)
        self.assertEqual(rules['rule'], [['A']])

if __name__ == '__main__':
    unittest.main()
