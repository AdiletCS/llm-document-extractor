import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from eval import calculate_metrics, main
from schemas import Document


class EvalTests(unittest.TestCase):
    def setUp(self):
        self.reference = json.loads(Path("data/expected/invoice_01.json").read_text(encoding="utf-8"))

    def test_identical_results(self):
        for counts in calculate_metrics(self.reference, self.reference).values():
            self.assertEqual(counts["correct"], counts["total"])
            self.assertEqual(counts["hallucinations"], 0)
            self.assertEqual(counts["omissions"], 0)

    def test_hallucinations_omissions_and_wrong_values_are_separate(self):
        actual = {**self.reference, "supplier_bin": None, "total_amount": 999, "currency": "EUR"}
        self.reference["currency"] = None
        metrics = calculate_metrics(self.reference, actual)
        self.assertEqual(metrics["currency"]["hallucinations"], 1)
        self.assertEqual(metrics["supplier_bin"]["omissions"], 1)
        self.assertEqual(metrics["total_amount"]["correct"], 0)
        self.assertEqual(metrics["total_amount"]["hallucinations"], 0)
        self.assertEqual(metrics["total_amount"]["omissions"], 0)

    def test_item_nulls(self):
        actual = {**self.reference, "line_items": [{"name": "Услуга", "qty": 2, "price": None}]}
        self.reference["line_items"] = [{"name": "Услуга", "qty": None, "price": 100}]
        metrics = calculate_metrics(self.reference, actual)
        self.assertEqual(metrics["line_items.qty"]["hallucinations"], 1)
        self.assertEqual(metrics["line_items.price"]["omissions"], 1)
        self.assertEqual(metrics["line_items"]["correct"], 0)

    def test_missing_and_extra_items(self):
        actual = {**self.reference, "line_items": []}
        metrics = calculate_metrics(self.reference, actual)
        self.assertEqual(metrics["line_items.name"]["omissions"], 2)
        metrics = calculate_metrics(actual, self.reference)
        self.assertEqual(metrics["line_items.name"]["hallucinations"], 2)

    def test_warning_text_is_compared_exactly(self):
        metrics = calculate_metrics(self.reference, {**self.reference, "warnings": ["Лишнее предупреждение"]})
        self.assertEqual(metrics["warnings"]["correct"], 0)
        self.assertEqual(metrics["warnings"]["hallucinations"], 0)

    def test_dataset_has_ten_valid_pairs(self):
        documents = {p.stem for p in Path("data/documents").glob("*.txt")}
        expected = {p.stem for p in Path("data/expected").glob("*.json")}
        self.assertEqual(len(documents), 10)
        self.assertEqual(documents, expected)
        for name in expected:
            with self.subTest(name=name):
                Document.model_validate_json(Path("data/expected", name + ".json").read_text(encoding="utf-8"))

    @patch("eval.extract_document", side_effect=OSError("API unavailable"))
    def test_unavailable_api_stops_without_fake_metrics(self, extract):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(), 1)
        extract.assert_called_once()
        self.assertIn("Метрики не рассчитаны", output.getvalue())
        self.assertIn("Успешно: 0/10", output.getvalue())

    @patch("eval.extract_document")
    def test_bad_reference_prevents_api_call(self, extract):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/documents").mkdir(parents=True)
            (root / "data/expected").mkdir()
            (root / "data/documents/test.txt").write_text("Текст", encoding="utf-8")
            (root / "data/expected/test.json").write_text("{}", encoding="utf-8")
            with patch("eval.__file__", str(root / "eval.py")), redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
        extract.assert_not_called()
