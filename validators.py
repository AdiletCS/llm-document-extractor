"""Ограниченные проверки БИН, итогов, НДС и дат документа."""

import re
from datetime import date
from decimal import Decimal

from schemas import Document


NUMERIC_AMOUNT = r"[+-]?[0-9]+(?:[ \u00a0\u202f][0-9]{3})*(?:[.,][0-9]{1,2})?"
WORD_NUMBERS = {
    "ноль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20, "тридцать": 30,
    "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90, "сто": 100, "двести": 200,
    "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
    "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
    "нөл": 0, "бір": 1, "екі": 2, "үш": 3, "төрт": 4, "бес": 5,
    "алты": 6, "жеті": 7, "сегіз": 8, "тоғыз": 9, "он": 10,
    "жиырма": 20, "отыз": 30, "қырық": 40, "елу": 50, "алпыс": 60,
    "жетпіс": 70, "сексен": 80, "тоқсан": 90,
}
SCALES = {"тысяча": 1000, "тысячи": 1000, "тысяч": 1000, "мың": 1000,
          "миллион": 1000000, "миллиона": 1000000, "миллионов": 1000000}
MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    "қаңтар": 1, "ақпан": 2, "наурыз": 3, "сәуір": 4,
    "мамыр": 5, "маусым": 6, "шілде": 7, "тамыз": 8,
    "қыркүйек": 9, "қазан": 10, "қараша": 11, "желтоқсан": 12,
}


def parse_amount(value: str) -> Decimal | None:
    numeric = re.fullmatch(
        rf"\s*({NUMERIC_AMOUNT})(?:\s*(?:тенге|теңге|тг|KZT|USD|EUR|евро|\$|€))?\s*\.?\s*",
        value, re.I,
    )
    if numeric:
        return Decimal(re.sub(r"\s", "", numeric[1]).replace(",", "."))
    # Поддерживаем целые суммы словами в тенге и цифровые тиыны, без догадок.
    words = re.fullmatch(r"\s*(.+?)\s+(?:тенге|теңге)(?:\s+([0-9]{1,2})\s+тиын)?\s*\.?\s*", value, re.I)
    if not words:
        return None
    total = group = 0
    previous = 1000
    previous_scale = 1000000000
    for word in words[1].casefold().split():
        if word in SCALES:
            scale = SCALES[word]
            if not group or scale >= previous_scale:
                return None
            total += group * scale
            group = 0
            previous = 1000
            previous_scale = scale
        elif word == "жүз":
            if group == 0 and previous == 1000:
                group = 100
            elif 0 < group < 10:
                group *= 100
            else:
                return None
            previous = 100
        elif word in WORD_NUMBERS:
            number = WORD_NUMBERS[word]
            if number >= previous or (previous < 100 and number >= 10) or (previous < 20 and number < 10):
                return None
            group += number
            previous = number
        else:
            return None
    return Decimal(total + group) + Decimal(words[2] or "0") / 100


def find_totals(text: str) -> set[Decimal]:
    # Итог к оплате имеет приоритет над промежуточным «Итого».
    final = r"^\s*(?:всего к оплате|итого к оплате|к оплате|общая сумма|жалпы сомасы)"
    matches = re.findall(final + r"\b\s*[:—-]?\s*([^\n]*)", text, re.I | re.M)
    if not matches:
        matches = re.findall(r"^\s*(?:итого|всего)\b\s*[:—-]?\s*([^\n]*)", text, re.I | re.M)
    totals = set()
    for value in matches:
        amount = parse_amount(value)
        if amount is not None:
            totals.add(amount)
    return totals


def find_dates(text: str) -> set[str]:
    date_text = r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}|\d{1,2}\s+[а-яёәіңғүұқөһ]+\s+\d{4}"
    pattern = rf"(?<!\w)(?:от|составлено|дата документа)\s*:?\s*({date_text})(?!\d)"
    matches = re.findall(pattern, text, re.I)
    # Дата после номера и '/' — только в заголовке счёта или акта.
    header = rf"^\s*(?:шот[ -]*фактура|сч[её]т|акт)[^\n]*?№[^\n]*?/\s*({date_text})(?!\d)"
    matches += re.findall(header, text, re.I | re.M)
    dates = set()
    for value in matches:
        if "." in value:
            day, month, year = value.split(".")
            value = f"{year}-{month}-{day}"
        try:
            parts = value.casefold().split()
            if len(parts) == 3:
                day, month, year = parts
                dates.add(date(int(year), MONTHS[month], int(day)).isoformat())
            else:
                dates.add(date.fromisoformat(value).isoformat())
        except (ValueError, KeyError):
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
            warnings.append("Итоговая сумма не подтверждена поддерживаемой строкой итога.")

    vat_values = set()
    vat_pattern = r"^\s*(?:ққс\s*/\s*ндс|ндс|ққс)\b\s*(?:[0-9]+(?:[.,][0-9]+)?\s*%\s*)?[:—-]?\s*([^\n]*)"
    for value in re.findall(vat_pattern, text, re.I | re.M):
        amount = parse_amount(value)
        if amount is not None:
            vat_values.add(amount)
    if len(vat_values) > 1:
        data["vat_amount"] = None
        warnings.append("В документе разные суммы НДС; vat_amount = null.")
    elif data["vat_amount"] is not None and Decimal(str(data["vat_amount"])) not in vat_values:
        data["vat_amount"] = None
        warnings.append("Сумма НДС не подтверждена явно указанной суммой; значение удалено.")

    dates = find_dates(text)
    if len(dates) > 1:
        data["doc_date"] = None
        warnings.append("В документе разные даты составления; doc_date = null.")
    elif data["doc_date"] is not None and data["doc_date"] not in dates:
        data["doc_date"] = None
        warnings.append("Дата документа не подтверждена поддерживаемой датой составления.")

    data["warnings"] = warnings
    return Document.model_validate(data)
