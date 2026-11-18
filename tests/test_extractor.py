"""Проверки ошибок без платных запросов к API."""

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from pydantic import ValidationError

from extractor import extract_document
from main import main


class ExtractorTests(unittest.TestCase):
    @patch("extractor.load_dotenv")
    @patch.dict("os.environ", {"OPENAI_API_KEY": ""})
    def test_missing_key(self, load_env):
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            extract_document("Документ")

    @patch("extractor.load_dotenv")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-placeholder"})
    @patch("extractor.OpenAI")
    def test_invalid_response(self, api, load_env):
        response = api.return_value.__enter__.return_value.responses.create.return_value
        response.status = "completed"
        response.output_text = '{"doc_type": "invented"}'
        with self.assertRaises(ValidationError):
            extract_document("Документ")
        schema = api.return_value.__enter__.return_value.responses.create.call_args.kwargs["text"]["format"]["schema"]
        self.assertFalse(schema["properties"]["field_confidence"]["additionalProperties"])

    @patch("extractor.load_dotenv")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-placeholder"})
    @patch("extractor.OpenAI")
    def test_incomplete_response(self, api, load_env):
        response = api.return_value.__enter__.return_value.responses.create.return_value
        response.status = "incomplete"
        with self.assertRaisesRegex(ValueError, "полный JSON"):
            extract_document("Документ")

    @patch("sys.argv", ["main.py", "missing-document.txt"])
    @patch("main.extract_document")
    def test_missing_file_does_not_call_api(self, extract):
        output = io.StringIO()
        with redirect_stderr(output):
            self.assertEqual(main(), 1)
        self.assertIn("Файл не найден", output.getvalue())
        extract.assert_not_called()
