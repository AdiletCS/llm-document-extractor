"""Проверки схемы, не требующие ключа API."""

import unittest

from pydantic import ValidationError

from schemas import Document


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "doc_type": "unknown",
            "supplier_name": None,
            "supplier_bin": None,
            "doc_number": None,
            "doc_date": None,
            "currency": None,
            "total_amount": None,
            "vat_amount": None,
            "line_items": [],
            "field_confidence": {},
            "warnings": [],
        }

    def test_nulls_and_json_round_trip(self):
        document = Document.model_validate(self.data)
        self.assertEqual(Document.model_validate_json(document.model_dump_json()), document)

    def test_filled_document(self):
        self.data.update(
            doc_type="invoice", supplier_name="ТОО Пример",
            supplier_bin="012345678901", doc_number="12", doc_date="2024-02-29",
            currency="KZT", total_amount=100, vat_amount=0,
            line_items=[{"name": "Бумага", "qty": 2, "price": 50}],
            field_confidence={"supplier_bin": 0.9}, warnings=["Пример"],
        )
        document = Document.model_validate_json(Document.model_validate(self.data).model_dump_json())
        self.assertEqual(document.supplier_bin, "012345678901")

    def test_invalid_values(self):
        for field, value in [
            ("doc_type", "receipt"), ("currency", "RUB"),
            ("supplier_bin", "123"), ("supplier_bin", "2l064090Ol80"),
            ("supplier_bin", "１２３４５６７８９０１２"),
            ("doc_date", "2026-02-30"), ("doc_date", "12.11.2026"),
            ("doc_date", "2026-1-01"),
            ("total_amount", "100"), ("vat_amount", True),
            ("total_amount", float("nan")), ("total_amount", float("inf")),
            ("field_confidence", {"supplier_bin": -0.1}),
            ("field_confidence", {"supplier_bin": 1.1}),
            ("line_items", [{"name": "Товар", "qty": "2", "price": None}]),
            ("line_items", [{"name": "Товар", "qty": None, "price": None, "extra": 1}]),
            ("warnings", [123]), ("extra", 1),
        ]:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValidationError):
                    Document.model_validate({**self.data, field: value})

    def test_every_field_is_required(self):
        for field in self.data:
            with self.subTest(field=field):
                incomplete = self.data.copy()
                del incomplete[field]
                with self.assertRaises(ValidationError):
                    Document.model_validate(incomplete)


if __name__ == "__main__":
    unittest.main()
