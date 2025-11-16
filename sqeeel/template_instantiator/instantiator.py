"""
Template instantiator.
"""

class TemplateInstantiator:
    """
    Converts a given template to a query for any given size nominator X.
    """
    def __init__(self, template):
        self.template = template

    def instantiate(self, size_nominator):
        """
        Instantiate the template with a given size nominator.
        """
        print(f"Instantiating template for size {size_nominator}...")
        return ""