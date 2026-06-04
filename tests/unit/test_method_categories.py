import unittest

from method_categories import classify_method_category_primary


class TestMethodCategories(unittest.TestCase):
    def test_implant_from_card(self):
        text = "[METHOD_CARD]NAME: Jadelle implant\nSUMMARY: Safe option[/METHOD_CARD]"
        self.assertEqual(classify_method_category_primary(text), "Implant")

    def test_iud_keyword(self):
        self.assertEqual(
            classify_method_category_primary("Consider copper IUD as first line."),
            "IUD",
        )

    def test_none_when_empty(self):
        self.assertIsNone(classify_method_category_primary(""))


if __name__ == "__main__":
    unittest.main()
