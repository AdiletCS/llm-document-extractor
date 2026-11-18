import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from main import main
from schemas import Document
from validators import validate_document


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.text = Path("data/documents/invoice_01.txt").read_text(encoding="utf-8")
        self.document = Document(
            doc_type="invoice", supplier_name='ТОО "Алматы Трейд Компани"',
            supplier_bin="170340021554", doc_number="1245", doc_date="2026-11-12",
            currency="KZT", total_amount=186180, vat_amount=25680,
            line_items=[], field_confidence={"supplier_bin": 0.0},
            warnings=["Возможно противоречие НДС"],
        )

    def test_correct_document(self):
        result = validate_document(self.text, self.document)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.total_amount, 186180)
        self.assertEqual(result.vat_amount, 25680)
        self.assertEqual(result.doc_date, "2026-11-12")
        self.assertEqual(result.field_confidence, {"supplier_bin": 1.0})
        self.assertEqual(self.document.field_confidence["supplier_bin"], 0)

    def test_missing_bin_removes_hallucination(self):
        result = validate_document(self.text.replace("БИН 170340021554", ""), self.document)
        self.assertIsNone(result.supplier_bin)
        self.assertEqual(result.field_confidence["supplier_bin"], 0)
        self.assertTrue(result.warnings)

    def test_missing_bin_and_null_need_no_warning(self):
        self.document.supplier_bin = None
        result = validate_document(self.text.replace("БИН 170340021554", ""), self.document)
        self.assertEqual(result.warnings, [])

    def test_bin_must_follow_label(self):
        result = validate_document(self.text.replace("БИН", "Телефон"), self.document)
        self.assertIsNone(result.supplier_bin)

    def test_ocr_bin_is_not_guessed(self):
        self.document.supplier_bin = None
        result = validate_document(self.text.replace("170340021554", "l70340021554"), self.document)
        self.assertIsNone(result.supplier_bin)
        self.assertTrue(result.warnings)

    def test_conflicting_totals(self):
        result = validate_document(self.text + "\nВсего к оплате: 200 000 тг", self.document)
        self.assertIsNone(result.total_amount)
        self.assertIn("разные итоговые суммы", result.warnings[0])

    def test_repeated_total_is_not_conflict(self):
        result = validate_document(self.text + "\nВсего к оплате: 186180,00 тг", self.document)
        self.assertEqual(result.warnings, [])

    def test_wrong_total_is_removed(self):
        self.document.total_amount = 160500
        result = validate_document(self.text, self.document)
        self.assertIsNone(result.total_amount)
        self.assertTrue(result.warnings)

    def test_conflicting_issue_dates(self):
        result = validate_document(self.text + "\nДата документа: 2026-11-13", self.document)
        self.assertIsNone(result.doc_date)
        self.assertTrue(result.warnings)

    def test_expiry_date_is_not_issue_date(self):
        result = validate_document(self.text + "\nДействительно до 30.11.2026", self.document)
        self.assertEqual(result.doc_date, "2026-11-12")
        self.assertEqual(result.warnings, [])

    @patch("sys.argv", ["main.py", "data/documents/invoice_01.txt"])
    @patch("main.extract_document")
    def test_cli_applies_validation(self, extract):
        extract.return_value = self.document
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["field_confidence"]["supplier_bin"], 1)
