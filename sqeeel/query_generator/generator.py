from collections import namedtuple
from typing import List, Optional
import networkx as nx

from sqeeel.query_generator.grammar_parser import parse_grammar
from sqeeel.query_generator.graph_builder import build_graph

def find_cycles(graph: nx.DiGraph, max_cycle_length: int) -> List[List[str]]:
    """
    Finds all simple cycles in a graph with a maximum length.
    """
    return list(nx.simple_cycles(graph, length_bound=max_cycle_length))

QueryTemplate = namedtuple('QueryTemplate', ['prefix', 'left', 'middle', 'right', 'suffix'])
class QueryGenerator:
    def __init__(self, grammar_file: str, max_cycle_length: int = 5):
        self.rules = parse_grammar(grammar_file)
        self.graph = build_graph(self.rules)
        self.cycles = find_cycles(self.graph, max_cycle_length)
        self.shortest_expansions = self._get_shortest_terminal_expansions()


    def generate_templates(self, start_token: str):
        templates = set()
        for cycle in self.cycles:
            # Find a single, representative entry point to the cycle
            entry_point = self._find_shortest_path_entry_point(start_token, cycle)
            if entry_point is None:
                continue
            
            path = nx.shortest_path(self.graph, start_token, entry_point)
            
            rotated_cycle = self._rotate_cycle(cycle, entry_point)
            
            # This function will now return a list of templates
            new_templates = self._construct_templates_for_path(path, rotated_cycle)
            templates.update(new_templates)
                
        return list(templates)

    def _find_shortest_path_entry_point(self, start_token: str, cycle: List[str]) -> Optional[str]:
        """
        Finds the entry point of a cycle that is reachable via the shortest path from the start token.
        """
        shortest_path_len = float('inf')
        entry_point = None
        for node in cycle:
            try:
                path_len = nx.shortest_path_length(self.graph, start_token, node)
                if path_len < shortest_path_len:
                    shortest_path_len = path_len
                    entry_point = node
            except nx.NetworkXNoPath:
                continue
        return entry_point

    def _rotate_cycle(self, cycle: List[str], entry_point: str) -> List[str]:
        """
        Rotates a cycle to start with the entry point.
        """
        entry_index = cycle.index(entry_point)
        return cycle[entry_index:] + cycle[:entry_index]


    def _get_shortest_terminal_expansions(self):
        expansions = {}
        
        # Initialize with terminals
        for rule in self.rules:
            for alternative in self.rules[rule]:
                for token in alternative:
                    if token not in self.rules:
                        expansions[token.strip("'")] = token.strip("'")

        # Iteratively build up expansions
        changed = True
        while changed:
            changed = False
            for rule, alternatives in self.rules.items():
                shortest_expansion = None
                for alternative in alternatives:
                    current_expansion = ""
                    current_expansion_list = []
                    possible = True
                    for token in alternative:
                        if token in expansions:
                            current_expansion_list.append(expansions[token])
                        else:
                            possible = False
                            break
                    if possible:
                        current_expansion = " ".join(current_expansion_list)
                    if possible:
                        if shortest_expansion is None or len(current_expansion) < len(shortest_expansion):
                            shortest_expansion = current_expansion
                
                if shortest_expansion is not None:
                    if rule not in expansions or len(shortest_expansion) < len(expansions[rule]):
                        expansions[rule] = shortest_expansion
                        changed = True
        return expansions


    def _construct_templates_for_path(self, path_to_cycle: List[str], cycle: List[str]) -> List[QueryTemplate]:
        # 1. Get cycle parts (constant for all templates from this path/cycle)
        breaking_point_node = cycle[-1]
        rule_name, alt_index_str = breaking_point_node.split(':')
        alt_index = int(alt_index_str)
        
        middle_alt = self._find_shortest_non_cyclic_alternative(rule_name, cycle)
        middle = " ".join(self.shortest_expansions.get(t, t) for t in middle_alt)

        cycle_alternative = self.rules[rule_name][alt_index]
        closing_token = next((t for t in cycle_alternative if t in cycle), None)
        if closing_token is None: return []
        closing_token_index = cycle_alternative.index(closing_token)
        
        left = " ".join(self.shortest_expansions.get(t, t) for t in cycle_alternative[:closing_token_index])
        right = " ".join(self.shortest_expansions.get(t, t) for t in cycle_alternative[closing_token_index+1:])

        # 2. Generate all (prefix, suffix) pairs for the path
        # A state is a tuple: (prefix_tokens, suffix_tokens)
        expansion_states = [([], [])]

        # Iterate over the path segments (rule -> alt -> next_rule)
        for i in range(0, len(path_to_cycle) - 2, 2):
            rule_name = path_to_cycle[i]
            alt_node = path_to_cycle[i+1]
            next_rule_on_path = path_to_cycle[i+2]

            _, alt_index_str = alt_node.split(':')
            alt_index = int(alt_index_str)
            alternative = self.rules[rule_name][alt_index]

            # Find all occurrences of the next rule in this alternative
            indices = [i for i, token in enumerate(alternative) if token == next_rule_on_path]
            
            new_states = []
            # For each previous state, create new branches for each occurrence
            for prev_prefix, prev_suffix in expansion_states:
                for index in indices:
                    # Tokens from the current alternative that are not the next step on the path
                    # need to be expanded to their shortest form.
                    
                    # Prefix part from this level
                    local_prefix = [self.shortest_expansions.get(t, t) for t in alternative[:index]]
                    
                    # Suffix part from this level
                    local_suffix = [self.shortest_expansions.get(t, t) for t in alternative[index+1:]]

                    # Combine with previous state
                    new_prefix = prev_prefix + local_prefix
                    new_suffix = local_suffix + prev_suffix
                    
                    new_states.append((new_prefix, new_suffix))
            
            expansion_states = new_states

        # 3. Create a final template for each expanded state
        templates = []
        for prefix_tokens, suffix_tokens in expansion_states:
            prefix = " ".join(prefix_tokens).strip()
            if prefix: prefix += " "
            
            left_str = left.strip()
            if left_str: left_str += " "
            
            middle_str = middle.strip()
            if middle_str: middle_str += " "
            
            right_str = right.strip()
            if right_str: right_str += " "

            suffix = " ".join(suffix_tokens).strip()
            templates.append(QueryTemplate(prefix, left_str, middle_str, right_str, suffix))
        
        return templates

    def _find_shortest_non_cyclic_alternative(self, rule_name: str, cycle: List[str]) -> List[str]:
        shortest_alt = None
        shortest_len = float('inf')
        for i, alternative in enumerate(self.rules[rule_name]):
            alt_node_name = f"{rule_name}:{i}"
            if alt_node_name not in cycle:
                # A simple heuristic for "shortest"
                if len(alternative) < shortest_len:
                    shortest_len = len(alternative)
                    shortest_alt = alternative
        return shortest_alt if shortest_alt is not None else []
