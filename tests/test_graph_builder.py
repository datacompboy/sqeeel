import unittest
import networkx as nx
from sqeeel.query_generator.grammar_parser import parse_grammar
from sqeeel.query_generator.graph_builder import build_graph

class TestGraphBuilder(unittest.TestCase):
    def test_build_graph(self):
        rules = parse_grammar('tests/sample.y')
        graph = build_graph(rules)
        
        self.assertIsInstance(graph, nx.DiGraph)
        
        # Check nodes
        expected_nodes = [
            'expr', 'expr:0', 'expr:1',
            'term', 'term:0', 'term:1',
            'factor', 'factor:0', 'factor:1',
            'selectExpr',  'selectExpr:0',
        ]
        self.assertCountEqual(list(graph.nodes), expected_nodes)
        
        # Check edges
        expected_edges = [
            ('expr', 'expr:0'), ('expr', 'expr:1'),
            ('expr:0', 'term'),
            ('expr:1', 'expr'), ('expr:1', 'term'),
            ('term', 'term:0'), ('term', 'term:1'),
            ('term:0', 'factor'),
            ('term:1', 'term'), ('term:1', 'factor'),
            ('factor', 'factor:0'), ('factor', 'factor:1'),
            ('factor:0', 'expr'),
            ('selectExpr', 'selectExpr:0'),
            ('selectExpr:0', 'expr'),
        ]
        self.assertCountEqual(list(graph.edges), expected_edges)

if __name__ == '__main__':
    unittest.main()