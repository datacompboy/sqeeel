"""
Template instantiator.
"""
import ast

def parse_template_string(template_str):
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
    Generates a bash one-liner for a query template.
    """
    escaped_sequence = [s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n') for s in sequence]
    tpl_str = "['" + "', '".join(escaped_sequence) + "']"
    
    # Python script to run
    script = (
        "import sys,itertools;e=enumerate;"
        "n=int(sys.stdin.read());"
        "c=itertools.count();"
        "sys.stdout.writelines("
            "str(next(c))+p if j else p "
            f"for i,s in e({tpl_str})"
            "for _ in range(max(1,n*(i%2)))"
            "for j,p in e(s.split('$'))"
        ")"
    )
    
    bash_script = script.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
    
    return f'python3 -c "{bash_script}" <<<$1'

class TemplateInstantiator:
    """
    Converts a given template to a query for any given size nominator X.
    """
    def __init__(self, template):
        self.parts = template
        self.compiled_parts = [self._compile(p) for p in self.parts]

    def _compile(self, part):
        """
        "Compiles" a template part by splitting it by '$' for later processing.
        """
        return part.split('$')

    def _instantiate_part(self, compiled_part, counter_ref):
        """
        Instantiates a pre-compiled template part.
        """
        if len(compiled_part) == 1:
            return compiled_part[0]
        
        result = [compiled_part[0]]
        for i in range(1, len(compiled_part)):
            result.append(str(counter_ref[0]))
            result.append(compiled_part[i])
            counter_ref[0] += 1
        return "".join(result)

    def instantiate(self, x):
        counter = [0]
        result_parts = []
        
        for i, compiled_part in enumerate(self.compiled_parts):
            if i % 2 == 0:
                # Even index (1st, 3rd...) -> Append once
                result_parts.append(self._instantiate_part(compiled_part, counter))
            else:
                # Odd index (2nd, 4th...) -> Repeat x times
                for _ in range(x):
                    result_parts.append(self._instantiate_part(compiled_part, counter))
        
        return "".join(result_parts)
