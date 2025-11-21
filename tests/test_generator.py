import unittest
from sqeeel.query_generator.generator import QueryGenerator, QueryTemplate

class TestQueryGenerator(unittest.TestCase):
    def test_find_cycles(self):
        generator = QueryGenerator('tests/sample.y', max_cycle_length=10)
        expected_cycles = [
            ['expr', 'expr:1'],
            ['term', 'term:1'],
            ['expr', 'expr:0', 'term', 'term:0', 'factor', 'factor:0'],
            ['expr', 'expr:1', 'term', 'term:0', 'factor', 'factor:0'],
            ['expr', 'expr:0', 'term', 'term:1', 'factor', 'factor:0'],
            ['expr', 'expr:1', 'term', 'term:1', 'factor', 'factor:0'],
        ]
        
        found_cycles_set = set(map(frozenset, generator.cycles))
        expected_cycles_set = set(map(frozenset, expected_cycles))

        self.assertEqual(found_cycles_set, expected_cycles_set)

    def test_find_shortest_path_entry_point(self):
        generator = QueryGenerator('tests/sample.y')
        cycle = ['expr', 'expr:1']
        entry_point = generator._find_shortest_path_entry_point('expr', cycle)
        self.assertEqual(entry_point, 'expr')

    def test_rotate_cycle(self):
        generator = QueryGenerator('tests/sample.y')
        cycle = ['expr:1', 'term', 'factor', 'expr']
        rotated_cycle = generator._rotate_cycle(cycle, 'term')
        self.assertEqual(rotated_cycle, ['term', 'factor', 'expr', 'expr:1'])

    def test_get_shortest_terminal_expansions(self):
        generator = QueryGenerator('tests/sample.y')
        expected_expansions = {
            'expr': 'NUMBER',
            'term': 'NUMBER',
            'factor': 'NUMBER',
            'NUMBER': 'NUMBER',
            '+': '+',
            '*': '*',
            '(': '(',
            ')': ')',
            'SELECT': 'SELECT',
            'WHERE': 'WHERE',
            'selectExpr': "SELECT NUMBER WHERE NUMBER"
        }
        self.assertEqual(generator.shortest_expansions, expected_expansions)

    def test_generate_templates_simple(self):
        generator = QueryGenerator('tests/sample.y', max_cycle_length=10)
        templates = generator.generate_templates('expr')
        
        expected_templates = {
            QueryTemplate(prefix='', left='', middle='NUMBER ', right='+ NUMBER ', suffix=''),
            QueryTemplate(prefix='', left='( ', middle='NUMBER ', right=') ', suffix=''),
            QueryTemplate(prefix='', left='', middle='NUMBER ', right='* NUMBER ', suffix=''),
            # Full-path cycles
            QueryTemplate(prefix='NUMBER * ', left='( ', middle='NUMBER ', right=') ', suffix=''),
            QueryTemplate(prefix='NUMBER + ', left='( ', middle='NUMBER ', right=') ', suffix=''),
            QueryTemplate(prefix='NUMBER + NUMBER * ', left='( ', middle='NUMBER ', right=') ', suffix=''),
        }
        
        self.assertSetEqual(set(templates), expected_templates)

    def test_generate_templates_recursive(self):
        generator = QueryGenerator('tests/recursive_sample.y', max_cycle_length=10)
        templates = generator.generate_templates('stmt')
        print("Recursive test templates:", templates)
        
        expected_templates = {
             QueryTemplate(prefix='PREFIX ', left='{ ( [ ', middle='{ ( MIDDLE ) } ', right='] ) } ', suffix='SUFFIX'),
        }
        
        self.assertSetEqual(set(templates), expected_templates)

    def test_generate_templates_multiple_paths(self):
        generator = QueryGenerator('tests/sample.y', max_cycle_length=10)
        templates = generator.generate_templates('selectExpr')

        expected_templates = {
            # First expr is a loop
            QueryTemplate(prefix='SELECT ', left='', middle='NUMBER ', right='* NUMBER ', suffix='WHERE NUMBER'),
            QueryTemplate(prefix='SELECT ', left='', middle='NUMBER ', right='+ NUMBER ', suffix='WHERE NUMBER'),
            QueryTemplate(prefix='SELECT ', left='( ', middle='NUMBER ', right=') ', suffix='WHERE NUMBER'),
            # Second expr is a loop
            QueryTemplate(prefix='SELECT NUMBER WHERE ', left='', middle='NUMBER ', right='* NUMBER ', suffix=''),
            QueryTemplate(prefix='SELECT NUMBER WHERE ', left='', middle='NUMBER ', right='+ NUMBER ', suffix=''),
            QueryTemplate(prefix='SELECT NUMBER WHERE ', left='( ', middle='NUMBER ', right=') ', suffix=''),
            # Full-path cycles
            QueryTemplate(prefix='SELECT NUMBER + ', left='( ', middle='NUMBER ', right=') ', suffix='WHERE NUMBER'),
            QueryTemplate(prefix='SELECT NUMBER + NUMBER * ', left='( ', middle='NUMBER ', right=') ', suffix='WHERE NUMBER'),
            QueryTemplate(prefix='SELECT NUMBER * ', left='( ', middle='NUMBER ', right=') ', suffix='WHERE NUMBER'),
            QueryTemplate(prefix='SELECT NUMBER WHERE NUMBER + NUMBER * ', left='( ', middle='NUMBER ', right=') ', suffix=''),
            QueryTemplate(prefix='SELECT NUMBER WHERE NUMBER + ', left='( ', middle='NUMBER ', right=') ', suffix=''),
            QueryTemplate(prefix='SELECT NUMBER WHERE NUMBER * ', left='( ', middle='NUMBER ', right=') ', suffix=''),
        }
        
        self.assertSetEqual(set(templates), expected_templates)

if __name__ == '__main__':
    unittest.main()
