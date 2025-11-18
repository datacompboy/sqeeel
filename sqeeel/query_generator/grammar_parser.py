import re
from typing import Dict, List, Tuple, Generator

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

def tokenize(text: str) -> Generator[Tuple[str, str], None, None]:
    """
    Tokenizes the rules section of a Bison grammar.
    Yields tuples of (token_type, token_value).
    """
    pos = 0
    length = len(text)
    while pos < length:
        char = text[pos]
        
        if char.isspace():
            pos += 1
            continue
        
        # Code block { ... }
        if char == '{':
            start = pos
            depth = 1
            pos += 1
            while pos < length and depth > 0:
                # Skip strings inside blocks to avoid matching braces inside them
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
                
                if text[pos] == '{':
                    depth += 1
                elif text[pos] == '}':
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

        # Directives %...
        if char == '%':
            start = pos
            pos += 1
            while pos < length and (text[pos].isalnum() or text[pos] == '_'):
                pos += 1
            yield ('DIRECTIVE', text[start:pos])
            continue

        # Identifiers
        if char.isalnum() or char == '_':
            start = pos
            # Bison identifiers can contain dots and underscores
            while pos < length and (text[pos].isalnum() or text[pos] in ('_', '.')):
                pos += 1
            yield ('ID', text[start:pos])
            continue
            
        # Symbols
        yield ('SYMBOL', text[pos])
        pos += 1

def parse_grammar(file_path: str) -> Dict[str, List[List[str]]]:
    """
    Parses a Bison-compatible grammar file and returns a map of rules.
    
    Returns a dictionary where keys are rule names and values are lists of alternatives.
    Each alternative is a list of tokens (strings).
    """
    with open(file_path, 'r') as f:
        content = f.read()

    clean_content = remove_comments(content)
    
    try:
        # Split sections by %%
        parts = clean_content.split('%%')
        if len(parts) < 2:
             return {}
        rules_section = parts[1]
    except IndexError:
        return {}

    tokens = list(tokenize(rules_section))
    rules: Dict[str, List[List[str]]] = {}
    
    current_rule = None
    current_alt: List[str] = []
    
    i = 0
    n = len(tokens)
    
    while i < n:
        typ, val = tokens[i]
        
        # Check for Rule Start: ID followed by :
        if typ == 'ID' and i + 1 < n and tokens[i+1] == ('SYMBOL', ':'):
            # Finish previous rule/alt if exists
            if current_rule:
                rules[current_rule].append(current_alt)
            
            current_rule = val
            if current_rule not in rules:
                rules[current_rule] = []
            current_alt = []
            i += 2 # Skip ID and :
            continue

        if typ == 'SYMBOL':
            if val == '|':
                if current_rule:
                    rules[current_rule].append(current_alt)
                    current_alt = []
                i += 1
                continue
            elif val == ';':
                if current_rule:
                    rules[current_rule].append(current_alt)
                    current_alt = []
                    current_rule = None
                i += 1
                continue
        
        if typ == 'DIRECTIVE':
            if val == '%prec':
                # Skip next token
                i += 2
                continue
            # Ignore other directives
            i += 1
            continue
            
        if typ == 'BLOCK':
            i += 1
            continue
            
        # Add token to current alt
        if current_rule:
            if typ == 'LITERAL':
                # Remove quotes for cleaner tokens
                current_alt.append(val.strip("'\""))
            else:
                current_alt.append(val)
        
        i += 1

    # Handle the last accumulated alternative if the file didn't end with a semicolon/directive
    if current_rule:
         rules[current_rule].append(current_alt)
        
    return rules