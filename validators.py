"""Ограниченные проверки БИН, числовых итогов и дат документа."""

import re
from datetime import date
from decimal import Decimal

from schemas import Document


def find_totals(text: str) -> set[Decimal]:
    # Итог к оплате имеет приоритет над промежуточным «Итого».
    amount = r"\s*[:—-]?\s*([+-]?[0-9]+(?:[ \u00a0\u202f][0-9]{3})*(?:[.,][0-9]{1,2})?)(?![0-9.,]|[ \u00a0\u202f]+[0-9])"
    final = r"^\s*(?:всего к оплате|итого к оплате|к оплате|общая сумма|жалпы сомасы)"
    matches = re.findall(final + amount, text, re.I | re.M)
    if not matches and not re.search(final + r"\b", text, re.I | re.M):
        matches = re.findall(r"^\s*(?:итого|всего)\b" + amount, text, re.I | re.M)
    return {Decimal(re.sub(r"\s", "", value).replace(",", ".")) for value in matches}


def find_dates(text: str) -> set[str]:
    pattern = r"(?<!\w)(?:от|составлено|дата документа)\s*:?\s*(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})(?!\d)"
    dates = set()
    for value in re.findall(pattern, text, re.I):
        if "." in value:
            day, month, year = value.split(".")
            value = f"{year}-{month}-{day}"
        try:
            dates.add(date.fromisoformat(value).isoformat())
        except ValueError:
            pass
    return dates


def validate_document(text: str, document: Document) -> Document:
    data = document.model_dump()
    # Свободный текст предупреждений LLM нельзя надёжно проверить.
    # Выдаём только предупреждения, для которых ниже есть конкретная проверка.
    warnings = []
    bins = set(re.findall(r"\b(?:БИН|БСН)(?:\s*/\s*(?:БИН|БСН))?\s*:?\s*([0-9]{12})(?!\w)", text, re.I))
    if data["supplier_bin"] is not None and data["supplier_bin"] not in bins:
        data["supplier_bin"] = None
        warnings.append("БИН не подтверждён рядом с меткой БИН/БСН; значение удалено.")
    elif not bins and re.search(r"\b(?:БИН|БСН)\b", text, re.I):
        warnings.append("Рядом с меткой БИН/БСН не найдены однозначные 12 цифр.")
    # Это индикатор совпадения, а не вероятность правильности ответа.
    data["field_confidence"] = {"supplier_bin": 1.0 if data["supplier_bin"] is not None else 0.0}

    totals = find_totals(text)
    if len(totals) > 1:
        data["total_amount"] = None
        warnings.append("В документе разные итоговые суммы; total_amount = null.")
    elif data["total_amount"] is not None:
        if totals and Decimal(str(data["total_amount"])) not in totals:
            data["total_amount"] = None
            warnings.append("Сумма не совпадает с итогом к оплате; значение удалено.")
        elif not totals:
            data["total_amount"] = None
            warnings.append("Итоговая сумма не подтверждена поддерживаемой числовой строкой.")

    dates = find_dates(text)
    if len(dates) > 1:
        data["doc_date"] = None
        warnings.append("В документе разные даты составления; doc_date = null.")
    elif data["doc_date"] is not None and data["doc_date"] not in dates:
        data["doc_date"] = None
        warnings.append("Дата документа не подтверждена поддерживаемой датой составления.")

    data["warnings"] = warnings
    return Document.model_validate(data)
