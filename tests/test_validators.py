import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch

from main import main
from schemas import Document
from validators import find_dates, find_totals, parse_amount, validate_document


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

    def test_written_amounts(self):
        for text, expected in [
            ("Сто двадцать тысяч тенге 00 тиын", "120000"),
            ("Үш жүз қырық мың теңге 00 тиын", "340000"),
            ("Двести пять тысяч тридцать один тенге 25 тиын", "205031.25"),
            ("Бір миллион екі жүз мың теңге", "1200000"),
            ("1 200,50 KZT", "1200.50"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(parse_amount(text), Decimal(expected))

    def test_unsupported_amounts_are_not_guessed(self):
        for text in ["сто двадцать неизвестных тенге", "примерно сто тенге",
                     "десять пять тенге", "сто сто тенге", "100,123 KZT"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_amount(text))

    def test_written_and_numeric_total_conflict(self):
        text = self.text + "\nВсего к оплате: Сто тысяч тенге"
        result = validate_document(text, self.document)
        self.assertIsNone(result.total_amount)
        self.assertTrue(result.warnings)

    def test_duplicate_written_total_is_not_conflict(self):
        self.assertEqual(find_totals("Всего к оплате: 120 000 тенге\nВсего к оплате: Сто двадцать тысяч тенге"), {Decimal(120000)})

    def test_word_dates_and_header_slash(self):
        for text, expected in [
            ("Счёт № D-3 от 9 октября 2026 г.", "2026-10-09"),
            ("Шот-фактура № AKT-09 / 09 қазан 2026 ж.", "2026-10-09"),
            ("Дата документа: 1\u00a0қаңтар\u00a02027", "2027-01-01"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(find_dates(text), {expected})

    def test_invalid_word_date_and_expiry_are_not_issue_dates(self):
        self.assertEqual(find_dates("Составлено 31 февраля 2026"), set())
        self.assertEqual(find_dates("Действительно до 9 октября 2026"), set())

    def test_written_date_conflicts_with_numeric_date(self):
        result = validate_document(self.text + "\nСоставлено 13 ноября 2026", self.document)
        self.assertIsNone(result.doc_date)
        self.assertTrue(result.warnings)

    def test_correct_word_values_survive_validation(self):
        for name in ["invoice_03", "invoice_10"]:
            with self.subTest(name=name):
                reference = Document.model_validate_json(Path("data/expected", name + ".json").read_text(encoding="utf-8"))
                text = Path("data/documents", name + ".txt").read_text(encoding="utf-8")
                self.assertEqual(validate_document(text, reference), reference)

    def test_vat_rate_and_exemption_are_not_amounts(self):
        for text in ["НДС 16%, сумма налога не указана.", "НДС не облагается", "Без НДС"]:
            with self.subTest(text=text):
                result = validate_document(text, self.document)
                self.assertIsNone(result.vat_amount)
                self.assertTrue(any("НДС" in warning for warning in result.warnings))

    def test_explicit_zero_vat_is_preserved(self):
        self.document.vat_amount = 0
        result = validate_document(self.text + "\nҚҚС / НДС: 0 теңге", self.document)
        # Две явно разные суммы НДС должны обнаруживаться как конфликт.
        self.assertIsNone(result.vat_amount)
        result = validate_document("ҚҚС / НДС: 0 теңге", self.document)
        self.assertEqual(result.vat_amount, 0)

    def test_validator_does_not_fill_missing_vat(self):
        self.document.vat_amount = None
        result = validate_document(self.text, self.document)
        self.assertIsNone(result.vat_amount)

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
