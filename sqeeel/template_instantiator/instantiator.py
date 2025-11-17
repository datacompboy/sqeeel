"""
Template instantiator.
"""

class TemplateInstantiator:
    """
    Converts a given template to a query for any given size nominator X.
    """
    def __init__(self, template):
        self.prefix, self.left, self.middle, self.right, self.suffix = template

    def instantiate(self, x):
        counter = 0
        
        def replace_dollar(s):
            nonlocal counter
            parts = s.split('$')
            result = [parts[0]]
            for part in parts[1:]:
                result.append(str(counter))
                result.append(part)
                counter += 1
            return "".join(result)

        final_prefix = replace_dollar(self.prefix)
        
        left_parts = []
        for _ in range(x):
            left_parts.append(replace_dollar(self.left))
        
        final_middle = replace_dollar(self.middle)
        
        right_parts = []
        for _ in range(x):
            right_parts.append(replace_dollar(self.right))

        final_suffix = replace_dollar(self.suffix)
        
        return final_prefix + "".join(left_parts) + final_middle + "".join(right_parts) + final_suffix