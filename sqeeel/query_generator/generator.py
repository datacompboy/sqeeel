from collections import namedtuple
from typing import List, Optional, Callable, Tuple, Set, Dict
import networkx as nx
import ast

from sqeeel.query_generator.grammar_parser import parse_grammar
from sqeeel.query_generator.graph_builder import build_graph

QueryTemplate = namedtuple('QueryTemplate', ['prefix', 'left', 'middle', 'right', 'suffix'])
def parse_template_string(template_str: str) -> Tuple:
    try:
        tpl = ast.literal_eval(template_str)
        if not isinstance(tpl, (tuple, list)):
            raise ValueError("Template must be a tuple of strings")
        if not all(isinstance(x, str) for x in tpl):
            raise ValueError("Template must be a tuple of strings")
        
        # Check that at least one repeatable part (odd indices) is non-empty
        odd_parts_len = sum(len(tpl[i]) for i in range(1, len(tpl), 2))
        if odd_parts_len == 0:
             raise ValueError("Template must have at least one non-empty repeatable part")

        return tuple(tpl)
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"Invalid template format: {e}")

def generate_cmd(sequence):
    """
    Generates a high-performance, syntactically correct Bash one-liner.
    Uses lambda and streaming to ensure single-line compatibility and speed.
    """
    # 1. Preamble & Helper Function (Lambda)
    # R = itertools.repeat, w = sys.stdout.writelines, n = input number
    # f = lambda s: Chunk and stream the repeated string s.
    # The list comprehension consumes the generator created by R()
    header = (
        "import sys,itertools;R=itertools.repeat;"
        "w=sys.stdout.writelines;n=int(input());"
        "f=lambda s,k=8192:[w(R(s*k,n//k)),w([s*(n%k)])]"
    )

    body = []

    # 2. Build the calls
    for i, text in enumerate(sequence):
        # Escape for Python string
        safe_text = text.replace("\\", "\\\\").replace("'", "\\'")

        if not text: continue

        if i % 2 == 0:
            # Constant: print once (wrapped in list for writelines)
            body.append(f"w(['{safe_text}'])")
        else:
            # Repeating: call the optimized lambda function 'f'
            body.append(f"f('{safe_text}')")

    # 3. Assemble and Escape for Bash
    # Note: We use a list comprehension in the main body to execute the lambda calls
    # without needing a multi-line loop.
    script = header + f";any(({','.join(body)}))"

    # Wrap in Bash: Escape double quotes for the bash argument
    bash_safe_code = script.replace('"', '\\"').replace("\\", "\\\\")

    return f'python3 -c "{bash_safe_code}"<<<$1'


class QueryGenerator:
    def __init__(self, grammar_file: str, max_cycle_length: int = 5,
                 grammar_token_rewriter: Optional[Callable[[str], str]] = None,
                 removed_rules: Optional[List[str]] = None,
                 template_token_rewriter: Optional[Callable[[str], str]] = None):
        self.rules = parse_grammar(grammar_file, grammar_token_rewriter, removed_rules)
        self.graph = build_graph(self.rules)
        self.template_token_rewriter = template_token_rewriter
        self.shortest_expansions = self._get_shortest_terminal_expansions()
        self.cycles = list(nx.simple_cycles(self.graph, length_bound=max_cycle_length))
        
    def generate_templates(self, start_token: str) -> List[QueryTemplate]:
        templates: Set[QueryTemplate] = set()

        for cycle_nodes in self.cycles:
            # 1. Find the shortest path from start_token to the cycle
            entry_point, path_to_cycle = self._find_shortest_path_to_cycle(start_token, cycle_nodes)
            
            if entry_point is None:
                continue # Cycle not reachable from start_token
            
            assert path_to_cycle is not None
                
            # 2. Rotate cycle to start at entry_point
            rotated_cycle = self._rotate_cycle(cycle_nodes, entry_point)
            
            # 3. Expand path to get prefixes and suffixes
            path_expansions = self._expand_path(path_to_cycle)
            
            # 4. Expand cycle to get lefts and rights
            # The cycle from nx.simple_cycles doesn't repeat the start node at the end.
            # We append entry_point to close it for expansion logic.
            cycle_path = rotated_cycle + [entry_point]
            loop_expansions = self._expand_loop(cycle_path)
            
            # 5. Middle is the shortest terminal expansion of the entry_point
            middle = self.shortest_expansions.get(entry_point, "")
            
            # Combine all parts
            for prefix, suffix in path_expansions:
                for left, right in loop_expansions:
                    # Ensure proper spacing
                    p = (prefix + " ") if prefix else ""
                    l = (left + " ") if left else ""
                    m = (middle + " ") if middle else ""
                    r = (right + " ") if right else ""
                    s = suffix if suffix else ""
                    
                    templates.add(QueryTemplate(p, l, m, r, s.strip()))

        return list(templates)

    def _find_shortest_path_to_cycle(self, start_token: str, cycle_nodes: List[str]) -> Tuple[Optional[str], Optional[List[str]]]:
        shortest_path = None
        shortest_len = float('inf')
        entry_point = None
        
        cycle_set = set(cycle_nodes)
        
        # Optimization: if start_token is in cycle, path is [start_token]
        if start_token in cycle_set:
             return start_token, [start_token]

        # Iterate over all nodes in cycle to find the one closest to start_token
        for node in cycle_nodes:
            # We only care about Rule nodes as entry points, not Alternative nodes (Rule:N)
            if ':' in node: 
                continue
                
            try:
                path = nx.shortest_path(self.graph, start_token, node)
                if len(path) < shortest_len:
                    shortest_len = len(path)
                    shortest_path = path
                    entry_point = node
            except nx.NetworkXNoPath:
                continue
                
        return entry_point, shortest_path

    def _rotate_cycle(self, cycle: List[str], entry_point: str) -> List[str]:
        try:
            idx = cycle.index(entry_point)
            return cycle[idx:] + cycle[:idx]
        except ValueError:
            return cycle

    def _get_token_str(self, token: str) -> str:
        if token in self.rules:
             return self.shortest_expansions.get(token, "")
        
        val = token.strip("'\"")
        if self.template_token_rewriter:
            val = self.template_token_rewriter(val)
        return val

    def _expand_path(self, path: List[str]) -> List[Tuple[str, str]]:
        current_states = [("", "")]
        
        for i in range(0, len(path) - 1, 2):
            rule_node = path[i]
            alt_node = path[i+1]
            next_rule_node = path[i+2] if i + 2 < len(path) else None
            
            if next_rule_node is None:
                break

            _, idx_str = alt_node.split(':')
            alt_idx = int(idx_str)
            
            tokens = self.rules[rule_node][alt_idx]
            indices = [j for j, t in enumerate(tokens) if t == next_rule_node]
            
            new_states = []
            for prev_prefix, prev_suffix in current_states:
                for idx in indices:
                    p_parts = [self._get_token_str(t) for t in tokens[:idx]]
                    local_prefix = " ".join(filter(None, p_parts))
                    
                    s_parts = [self._get_token_str(t) for t in tokens[idx+1:]]
                    local_suffix = " ".join(filter(None, s_parts))
                    
                    combo_prefix = (prev_prefix + " " + local_prefix).strip()
                    combo_suffix = (local_suffix + " " + prev_suffix).strip()
                    
                    new_states.append((combo_prefix, combo_suffix))
            
            current_states = new_states
            
        return current_states

    def _expand_loop(self, cycle_path: List[str]) -> List[Tuple[str, str]]:
        current_states = [("", "")]
        
        for i in range(0, len(cycle_path) - 1, 2):
            rule_node = cycle_path[i]
            alt_node = cycle_path[i+1]
            next_rule_node = cycle_path[i+2]
            
            _, idx_str = alt_node.split(':')
            alt_idx = int(idx_str)
            tokens = self.rules[rule_node][alt_idx]
            
            indices = [j for j, t in enumerate(tokens) if t == next_rule_node]
            
            new_states = []
            for prev_left, prev_right in current_states:
                for idx in indices:
                    l_parts = [self._get_token_str(t) for t in tokens[:idx]]
                    local_left = " ".join(filter(None, l_parts))
                    
                    r_parts = [self._get_token_str(t) for t in tokens[idx+1:]]
                    local_right = " ".join(filter(None, r_parts))
                    
                    combo_left = (prev_left + " " + local_left).strip()
                    combo_right = (local_right + " " + prev_right).strip()
                    
                    new_states.append((combo_left, combo_right))
            
            current_states = new_states
            
        return current_states

    def _get_shortest_terminal_expansions(self) -> Dict[str, str]:
        expansions = {}
        
        changed = True
        while changed:
            changed = False
            for rule, alternatives in self.rules.items():
                best_expansion = expansions.get(rule)
                
                for alternative in alternatives:
                    current_parts = []
                    possible = True
                    for token in alternative:
                        if token in self.rules:
                            if token in expansions:
                                current_parts.append(expansions[token])
                            else:
                                possible = False
                                break
                        else:
                            val = token.strip("'\"")
                            if self.template_token_rewriter:
                                val = self.template_token_rewriter(val)
                            current_parts.append(val)
                    
                    if possible:
                        candidate = " ".join(filter(None, current_parts))
                        if best_expansion is None or len(candidate) < len(best_expansion):
                            best_expansion = candidate
                            
                if best_expansion is not None and (rule not in expansions or best_expansion != expansions[rule]):
                    expansions[rule] = best_expansion
                    changed = True
                    
        return expansions
