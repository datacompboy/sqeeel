"""
Template instantiator.
"""

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