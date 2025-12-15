import re
from typing import Dict, List, Tuple, Generator, Optional, Callable

def remove_comments(text: str) -> str:
    """
    Removes C-style /* ... */ and // ... comments from text.
    Preserves comments inside strings.
    """
    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            return " "
        else:
            return s
    # Regex matches comments OR strings. If string matches, we keep it. If comment matches, we replace it.
    # For // comments, we match until end of line. We use [^\n]* to assume . doesn't match newline.
    pattern = re.compile(
        r'//[^\n]*|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    return re.sub(pattern, replacer, text)

def tokenize_antlr(text: str) -> Generator[Tuple[str, str], None, None]:
    """
    Tokenizes an ANTLR grammar.
    Handles blocks {...} and [...] as skipped blocks.
    """
    pos = 0
    length = len(text)
    while pos < length:
        char = text[pos]
        
        if char.isspace():
            pos += 1
            continue
        
        # Code block { ... } or [ ... ]
        if char in ('{', '['):
            start = pos
            opener = char
            closer = '}' if opener == '{' else ']'
            depth = 1
            pos += 1
            while pos < length and depth > 0:
                if text[pos] in ("'", '"'):
                    quote = text[pos]
                    pos += 1
                    while pos < length and text[pos] != quote:
                        if text[pos] == '\\':
                            pos += 1
                        pos += 1
                    if pos < length:
                        pos += 1
                    continue
                
                if text[pos] == opener:
                    depth += 1
                elif text[pos] == closer:
                    depth -= 1
                pos += 1
            yield ('BLOCK', text[start:pos])
            continue

        # Strings '...' or "..."
        if char in ("'", '"'):
            quote = char
            start = pos
            pos += 1
            while pos < length and text[pos] != quote:
                if text[pos] == '\\':
                    pos += 1
                pos += 1
            pos += 1
            yield ('LITERAL', text[start:pos])
            continue

        # Identifiers
        if char.isalnum() or char == '_':
            start = pos
            while pos < length and (text[pos].isalnum() or text[pos] == '_'):
                pos += 1
            yield ('ID', text[start:pos])
            continue
            
        # Symbols
        yield ('SYMBOL', text[pos])
        pos += 1

def parse_antlr_body(
    tokens: List[Tuple[str, str]], 
    rules_dict: Dict[str, List[List[str]]],
    rule_name_gen: Callable[[], str],
    token_rewriter: Optional[Callable[[str], str]]
) -> List[List[str]]:
    """
    Parses a list of tokens representing the body of a rule (RHS).
    Returns list of alternatives (each alt is list of strings).
    Populates rules_dict with synthetic rules as needed.
    """
    alts = []
    current_alt = []
    
    i = 0
    n = len(tokens)
    while i < n:
        typ, val = tokens[i]
        
        if typ == 'SYMBOL':
            if val == '|':
                alts.append(current_alt)
                current_alt = []
                i += 1
                continue
            elif val == '(':
                # Nested block
                depth = 1
                j = i + 1
                sub_tokens = []
                while j < n and depth > 0:
                    if tokens[j] == ('SYMBOL', '('):
                        depth += 1
                    elif tokens[j] == ('SYMBOL', ')'):
                        depth -= 1
                    
                    if depth > 0:
                        sub_tokens.append(tokens[j])
                    j += 1
                
                syn_name = rule_name_gen()
                syn_alts = parse_antlr_body(sub_tokens, rules_dict, rule_name_gen, token_rewriter)
                rules_dict[syn_name] = syn_alts
                current_alt.append(syn_name)
                
                i = j # Move past )
                
                # Check for quantifier immediately after )
                if i < n and tokens[i][0] == 'SYMBOL' and tokens[i][1] in ['?', '*', '+']:
                    quant = tokens[i][1]
                    # We need to wrap the block rule (syn_name) with quantifier logic
                    prev = current_alt.pop() # Remove syn_name
                    wrapper = rule_name_gen()
                    
                    if quant == '?':
                        rules_dict[wrapper] = [[prev], []]
                    elif quant == '*':
                        rules_dict[wrapper] = [[prev, wrapper], []]
                    elif quant == '+':
                        rules_dict[wrapper] = [[prev, wrapper], [prev]]
                        
                    current_alt.append(wrapper)
                    i += 1
                continue
            
            elif val in ['?', '*', '+']:
                # Quantifier on previous token (non-paren)
                if current_alt:
                    prev = current_alt.pop()
                    syn_name = rule_name_gen()
                    
                    if val == '?':
                        rules_dict[syn_name] = [[prev], []]
                    elif val == '*':
                        rules_dict[syn_name] = [[prev, syn_name], []]
                    elif val == '+':
                        rules_dict[syn_name] = [[prev, syn_name], [prev]]
                        
                    current_alt.append(syn_name)
                i += 1
                continue
            
            elif val == '=' or val == '+=':
                 # Label: prev was label name. Pop it.
                 if current_alt:
                     current_alt.pop()
                 i += 1
                 continue
                 
            elif val == '.':
                 current_alt.append(val)
                 i += 1
                 continue
        
        if typ == 'ID':
             # Check for token or rule
             name = val
             if token_rewriter:
                 name = token_rewriter(name)
             current_alt.append(name)
             i += 1
             continue
             
        if typ == 'LITERAL':
             val_stripped = val.strip("'\"")
             if token_rewriter:
                 val_stripped = token_rewriter(val_stripped)
             current_alt.append(val_stripped)
             i += 1
             continue
             
        if typ == 'BLOCK':
             # Skip actions
             i += 1
             continue

        i += 1
        
    alts.append(current_alt)
    return alts

def parse_antlr_grammar(
    file_path: str,
    token_rewriter: Optional[Callable[[str], str]] = None,
    removed_rules: Optional[List[str]] = None
) -> Dict[str, List[List[str]]]:
    """
    Parses an ANTLR grammar file and returns a map of rules.
    Ignores actions, labels, and lexer rules (starting with uppercase).
    """
    with open(file_path, 'r') as f:
        content = f.read()

    clean_content = remove_comments(content)
    tokens = list(tokenize_antlr(clean_content))
    rules: Dict[str, List[List[str]]] = {}
    
    synthetic_counter = 0
    def next_synthetic():
        nonlocal synthetic_counter
        synthetic_counter += 1
        return f"__synthetic_{synthetic_counter}"

    i = 0
    n = len(tokens)
    
    while i < n:
        typ, val = tokens[i]
        
        # Look for Parser Rule Definition (ID start lowercase)
        if typ == 'ID':
            is_lexer = val[0].isupper() or val == 'fragment'
            
            # Lookahead to confirm it's a rule definition
            j = i + 1
            is_rule_def = False
            while j < n:
                t_typ, t_val = tokens[j]
                if t_typ == 'SYMBOL' and t_val == ':':
                    is_rule_def = True
                    break
                if t_typ == 'BLOCK': 
                    j += 1
                    continue
                if t_typ == 'ID' and t_val in ['returns', 'locals']: 
                     j += 1
                     continue
                if t_typ == 'SYMBOL' and t_val == '@': # @init
                     j += 1
                     if j < n and tokens[j][0] == 'ID': j += 1
                     if j < n and tokens[j][0] == 'BLOCK': j += 1
                     continue
                break
            
            if is_rule_def:
                if is_lexer:
                    # Skip lexer rule body until ;
                    while i < n:
                        if tokens[i] == ('SYMBOL', ';'):
                            i += 1
                            break
                        i += 1
                    continue
                
                # Found parser rule
                rule_name = val
                if token_rewriter:
                    rule_name = token_rewriter(rule_name)
                
                # Skip to :
                while i < n and not (tokens[i][0] == 'SYMBOL' and tokens[i][1] == ':'):
                    i += 1
                i += 1 # Skip :
                
                # Collect body tokens until ;
                body_tokens = []
                while i < n:
                    if tokens[i] == ('SYMBOL', ';'):
                        i += 1
                        break
                    body_tokens.append(tokens[i])
                    i += 1
                
                # Parse body
                alts = parse_antlr_body(body_tokens, rules, next_synthetic, token_rewriter)
                rules[rule_name] = alts
                continue
        
        i += 1
        continue
            
    if removed_rules:
        for rule in removed_rules:
            if rule in rules:
                del rules[rule]
                
    return rules
