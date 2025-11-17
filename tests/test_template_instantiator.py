import unittest
from sqeeel.template_instantiator.instantiator import TemplateInstantiator

class TestTemplateInstantiator(unittest.TestCase):
    def test_simple_instantiation(self):
        template = ('SELECT ', '(1+', '1', ')', '')
        instantiator = TemplateInstantiator(template)
        self.assertEqual(instantiator.instantiate(3), "SELECT (1+(1+(1+1)))")

    def test_dollar_replacement(self):
        template = ('SELECT ', '$+', '$', '', '')
        instantiator = TemplateInstantiator(template)
        self.assertEqual(instantiator.instantiate(3), "SELECT 0+1+2+3")

    def test_no_x(self):
        template = ('SELECT ', '1', '2', '3', '4')
        instantiator = TemplateInstantiator(template)
        self.assertEqual(instantiator.instantiate(0), "SELECT 24")

    def test_mixed(self):
        template = ('INSERT INTO t$ VALUES ', '($), ', '($)', ', ($)', ', ($);')
        instantiator = TemplateInstantiator(template)
        self.assertEqual(instantiator.instantiate(2), "INSERT INTO t0 VALUES (1), (2), (3), (4), (5), (6);")

if __name__ == '__main__':
    unittest.main()