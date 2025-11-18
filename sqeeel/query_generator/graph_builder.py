from typing import Dict, List
import networkx as nx

def build_graph(rules: Dict[str, List[List[str]]]) -> nx.DiGraph:
    """
    Builds a directed graph from a grammar map.
    """
    graph = nx.DiGraph()
    for rule_name, alternatives in rules.items():
        graph.add_node(rule_name)
        for i, alternative in enumerate(alternatives):
            alt_node_name = f"{rule_name}:{i}"
            graph.add_node(alt_node_name)
            graph.add_edge(rule_name, alt_node_name)
            for token in alternative:
                if token in rules:
                    graph.add_edge(alt_node_name, token)
    return graph