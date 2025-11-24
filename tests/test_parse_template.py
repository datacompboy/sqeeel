import unittest
from sqeeel.query_generator.generator import parse_template_string, QueryTemplate

class TestParseTemplate(unittest.TestCase):
    def test_valid_template(self):
        tpl_str = "('prefix ', 'left ', 'middle ', 'right ', 'suffix')"
        tpl = parse_template_string(tpl_str)
        self.assertEqual(tpl.prefix, 'prefix ')
        self.assertEqual(tpl.left, 'left ')
        self.assertEqual(tpl.middle, 'middle ')
        self.assertEqual(tpl.right, 'right ')
        self.assertEqual(tpl.suffix, 'suffix')

    def test_empty_template(self):
        tpl_str = "('', '', '', '', '')"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("non-empty left or right", str(cm.exception))

    def test_static_template(self):
        # No left/right
        tpl_str = "('prefix', '', 'middle', '', 'suffix')"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("non-empty left or right", str(cm.exception))

    def test_valid_cycle(self):
        # Only left
        tpl_str = "('', 'left', 'middle', '', '')"
        tpl = parse_template_string(tpl_str)
        self.assertEqual(tpl.left, 'left')

        # Only right
        tpl_str = "('', '', 'middle', 'right', '')"
        tpl = parse_template_string(tpl_str)
        self.assertEqual(tpl.right, 'right')

    def test_invalid_tuple_length(self):
        tpl_str = "('1', '2', '3')"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("5-tuple", str(cm.exception))

    def test_invalid_types(self):
        tpl_str = "('1', 1, '3', '4', '5')"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("5-tuple of strings", str(cm.exception))

    def test_not_a_tuple(self):
        tpl_str = "['1', '2', '3', '4', '5']"
        # My code accepts list or tuple: isinstance(tpl, (tuple, list))
        tpl = parse_template_string(tpl_str)
        self.assertIsInstance(tpl, QueryTemplate)

    def test_syntax_error(self):
        tpl_str = "('1', '2'"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("Invalid template format", str(cm.exception))

if __name__ == '__main__':
    unittest.main()
