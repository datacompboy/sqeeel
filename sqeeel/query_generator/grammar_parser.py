import re
from typing import Dict, List

def parse_grammar(file_path: str) -> Dict[str, List[List[str]]]:
    """
    Parses a Bison-compatible grammar file and returns a map of rules.
    """
    with open(file_path, 'r') as f:
        content = f.read()

    # Skip everything before the first %%
    try:
        rules_section = content.split('%%')[1]
    except IndexError:
        return {}

    rules: Dict[str, List[List[str]]] = {}
    # Split rules by semicolon, but not if it's inside a string
    rule_texts = [r.strip() for r in rules_section.strip().split(';') if r.strip()]

    for rule_text in rule_texts:
        if not rule_text:
            continue
        
        name, alternatives_text = rule_text.split(':', 1)
        name = name.strip()
        
        alternatives = []
        # Split alternatives by pipe
        for alt_text in alternatives_text.split('|'):
            tokens = [token.strip("'") for token in alt_text.strip().split()]
            if tokens:
                alternatives.append(tokens)
        
        if name in rules:
            rules[name].extend(alternatives)
        else:
            rules[name] = alternatives
            
    return rules