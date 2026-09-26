import sys
import types
import unittest
from unittest.mock import patch

from anki_pipeline.pdf import extract_examples


class _Page:
    def __init__(self, text):
        self.text = text

    def get_text(self):
        return self.text


class _Document:
    def __init__(self, pages):
        self.pages = [_Page(text) for text in pages]

    def __enter__(self):
        return self.pages

    def __exit__(self, *_):
        return False


class PdfTests(unittest.TestCase):
    def test_extracts_source_and_exact_forms_across_pages(self):
        pages = [
            "2020年全国硕士研究生招生考试英语（一）\n"
            "Section II Reading Comprehension\nPart A\nText 1\n"
            "A fair rate was offered to every customer.\n"
            "The theme of the chapter was clear to readers.\n",
            "Text 2\nThe higher fees affected several students.\n"
            "They rather liked the result, and them all agreed.\n"
            "The numbers were rated by the examiner.\n",
        ]
        fake_fitz = types.SimpleNamespace(open=lambda _: _Document(pages))
        with patch.dict(sys.modules, {"fitz": fake_fitz}):
            result = extract_examples("exam.pdf", ["rate", "theme", "fee"])

        self.assertEqual([len(result[word]) for word in ("rate", "theme", "fee")], [2, 1, 1])
        self.assertEqual(result["rate"][0]["text"], "A fair rate was offered to every customer.")
        self.assertIn("2020年英语（一）", result["rate"][0]["source"])
        self.assertIn("Section II", result["rate"][0]["source"])
        self.assertIn("Text 1", result["rate"][0]["source"])
        self.assertIn("第1页", result["rate"][0]["source"])
        self.assertIn("Text 2", result["fee"][0]["source"])
        self.assertIn("第2页", result["fee"][0]["source"])

    def test_discards_directions_and_preserves_decimal(self):
        pages = [
            "2019年全国硕士研究生招生考试英语（二）\nSection I\n"
            "Directions: Write a rate essay for this test.\n"
            "Use the rate in your answer. (10 points)\n"
            "The rate grew by 13.5 percent in the U.S. market.\n"
        ]
        fake_fitz = types.SimpleNamespace(open=lambda _: _Document(pages))
        with patch.dict(sys.modules, {"fitz": fake_fitz}):
            result = extract_examples("exam.pdf", ["rate"])
        self.assertEqual(len(result["rate"]), 1)
        self.assertEqual(result["rate"][0]["text"], "The rate grew by 13.5 percent in the U.S. market.")


if __name__ == "__main__":
    unittest.main()
