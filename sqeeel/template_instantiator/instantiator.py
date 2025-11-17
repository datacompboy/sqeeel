"""
Template instantiator.
"""

class TemplateInstantiator:
    """
    Converts a given template to a query for any given size nominator X.
    """
    def __init__(self, template):
        self.prefix, self.left, self.middle, self.right, self.suffix = template
        self._compiled_prefix = self._compile(self.prefix)
        self._compiled_left = self._compile(self.left)
        self._compiled_middle = self._compile(self.middle)
        self._compiled_right = self._compile(self.right)
        self._compiled_suffix = self._compile(self.suffix)

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
        
        final_prefix = self._instantiate_part(self._compiled_prefix, counter)
        
        left_parts = []
        for _ in range(x):
            left_parts.append(self._instantiate_part(self._compiled_left, counter))
        
        final_middle = self._instantiate_part(self._compiled_middle, counter)
        
        right_parts = []
        for _ in range(x):
            right_parts.append(self._instantiate_part(self._compiled_right, counter))

        final_suffix = self._instantiate_part(self._compiled_suffix, counter)
        
        return final_prefix + "".join(left_parts) + final_middle + "".join(right_parts) + final_suffix