import unittest
from sqeeel.query_generator.grammar_parser import parse_grammar

class TestGrammarParser(unittest.TestCase):
    def test_parse_grammar_simple(self):
        rules = parse_grammar('tests/sample.y')
        expected_rules = {
            'selectExpr': [['SELECT', 'expr', 'WHERE', 'expr']],
            'expr': [['term'], ['expr', '+', 'term']],
            'term': [['factor'], ['term', '*', 'factor']],
            'factor': [['(', 'expr', ')'], ['NUMBER']]
        }
        self.assertEqual(rules, expected_rules)

    def test_parse_grammar_complex(self):
        rules = parse_grammar('tests/complex_sample.y')
        expected_rules = {
            'stmt': [
                ['expr', ';'],
                []
            ],
            'expr': [
                ['expr', '+', 'term'],
                ['expr', '-', 'term'],
                ['term']
            ],
            'term': [
                ['term', '*', 'factor'],
                ['factor']
            ],
            'factor': [
                ['(', 'expr', ')'],
                ['NUMBER']
            ]
        }
        self.assertEqual(rules, expected_rules)

    def test_parse_real_grammar(self):
        rules = parse_grammar('grammars/pg19gram.y')
        self.assertIn('SelectStmt', rules)
        self.assertIn('InsertStmt', rules)
        
        # Check if comments are removed correctly
        # Ensure no rules contain C-style comments like /* ... */
        for rule_name, alts in rules.items():
            for alt in alts:
                for token in alt:
                    self.assertFalse(token.startswith('/*'))
                    self.assertFalse(token.startswith('//'))

    def test_parse_grammar_with_mutator(self):
        def mutator(rules):
            rules['new_rule'] = [['foo']]
            rules['expr'] = [['modified']]

        rules = parse_grammar('tests/sample.y', rules_mutator=mutator)
        self.assertIn('new_rule', rules)
        self.assertEqual(rules['new_rule'], [['foo']])
        self.assertEqual(rules['expr'], [['modified']])

if __name__ == '__main__':
    unittest.main()