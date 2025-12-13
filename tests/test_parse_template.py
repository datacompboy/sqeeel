import unittest
from sqeeel.query_generator.generator import parse_template_string

class TestParseTemplate(unittest.TestCase):
    def test_valid_template(self):
        tpl_str = "('prefix ', 'left ', 'middle ', 'right ', 'suffix')"
        tpl = parse_template_string(tpl_str)
        self.assertIsInstance(tpl, tuple)
        self.assertEqual(len(tpl), 5)
        self.assertEqual(tpl[0], 'prefix ')
        self.assertEqual(tpl[1], 'left ')
        self.assertEqual(tpl[2], 'middle ')
        self.assertEqual(tpl[3], 'right ')
        self.assertEqual(tpl[4], 'suffix')

    def test_empty_template(self):
        tpl_str = "('', '', '', '', '')"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("non-empty repeatable part", str(cm.exception))

    def test_static_template(self):
        # No left/right (indices 1 and 3 are empty)
        tpl_str = "('prefix', '', 'middle', '', 'suffix')"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("non-empty repeatable part", str(cm.exception))

    def test_valid_cycle(self):
        # Only left
        tpl_str = "('', 'left', 'middle', '', '')"
        tpl = parse_template_string(tpl_str)
        self.assertEqual(tpl[1], 'left')

        # Only right
        tpl_str = "('', '', 'middle', 'right', '')"
        tpl = parse_template_string(tpl_str)
        self.assertEqual(tpl[3], 'right')

    def test_arbitrary_length_valid(self):
        # 3-tuple: Fixed, Mult, Fixed. Mult='2' (len 1). Valid.
        tpl_str = "('1', '2', '3')"
        tpl = parse_template_string(tpl_str)
        self.assertEqual(tpl, ('1', '2', '3'))
    
    def test_arbitrary_length_invalid(self):
        # 3-tuple: Fixed, Mult, Fixed. Mult='' (len 0). Invalid.
        tpl_str = "('1', '', '3')"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("non-empty repeatable part", str(cm.exception))

    def test_invalid_types(self):
        tpl_str = "('1', 1, '3', '4', '5')"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("tuple of strings", str(cm.exception))

    def test_not_a_tuple(self):
        tpl_str = "['1', '2', '3', '4', '5']"
        # My code accepts list or tuple: isinstance(tpl, (tuple, list))
        tpl = parse_template_string(tpl_str)
        self.assertIsInstance(tpl, tuple)
        self.assertEqual(tpl, ('1', '2', '3', '4', '5'))

    def test_syntax_error(self):
        tpl_str = "('1', '2'"
        with self.assertRaises(ValueError) as cm:
            parse_template_string(tpl_str)
        self.assertIn("Invalid template format", str(cm.exception))

if __name__ == '__main__':
    unittest.main()
