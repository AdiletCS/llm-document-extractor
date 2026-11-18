"""python eval.py — один проход по документам через тот же пайплайн, что и CLI."""

import sys
from pathlib import Path

from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError

from extractor import extract_document
from schemas import Document
from validators import validate_document


def calculate_metrics(expected: dict, actual: dict) -> dict:
    pairs = [(field, value, actual[field]) for field, value in expected.items()]
    # Позиции сравниваем по порядку; отсутствующая позиция означает отсутствие её полей.
    for index in range(max(len(expected["line_items"]), len(actual["line_items"]))):
        expected_item = expected["line_items"][index] if index < len(expected["line_items"]) else {}
        actual_item = actual["line_items"][index] if index < len(actual["line_items"]) else {}
        for field in ("name", "qty", "price"):
            pairs.append((f"line_items.{field}", expected_item.get(field), actual_item.get(field)))

    metrics = {}
    for field, reference, prediction in pairs:
        counts = metrics.setdefault(field, {"correct": 0, "total": 0, "hallucinations": 0, "omissions": 0})
        counts["total"] += 1
        counts["correct"] += reference == prediction
        counts["hallucinations"] += reference is None and prediction is not None
        counts["omissions"] += reference is not None and prediction is None
    return metrics


def main() -> int:
    data = Path(__file__).parent / "data"
    documents = sorted((data / "documents").glob("*.txt"))
    expected_paths = sorted((data / "expected").glob("*.json"))
    if not documents or {p.stem for p in documents} != {p.stem for p in expected_paths}:
        print("Ошибка: нужны TXT и эталонный JSON с одинаковыми именами для каждого документа.")
        return 1
    # Проверяем весь набор до первого платного запроса.
    try:
        texts = {p.stem: p.read_text(encoding="utf-8-sig") for p in documents}
        references = {p.stem: Document.model_validate_json(p.read_text(encoding="utf-8")) for p in expected_paths}
        if any(not text.strip() for text in texts.values()):
            raise ValueError("Пустой TXT")
    except (OSError, ValueError):
        print("Ошибка: не удалось прочитать набор или эталон не соответствует схеме.")
        return 1

    totals = {}
    succeeded = failed = 0
    for path in documents:
        print(f"Обработка {path.name}...", flush=True)
        try:
            raw = extract_document(texts[path.stem])
            actual = validate_document(texts[path.stem], raw)
        except (APIConnectionError, AuthenticationError, RateLimitError, OSError):
            print("API недоступен: соединение, ключ, квота или TLS-настройки. Оценка остановлена.")
            failed += 1
            break
        except (APIError, ValueError):
            print("Ошибка API, настроек или невалидный ответ; документ не оценён.")
            failed += 1
            continue
        expected = references[path.stem].model_dump()
        prediction = actual.model_dump()
        for field, value in expected.items():
            if value != prediction[field]:
                print(f"  {field}: эталон={value!r}; результат={prediction[field]!r}")
                if getattr(raw, field) != prediction[field]:
                    print(f"    до валидации={getattr(raw, field)!r}")
        metrics = calculate_metrics(expected, prediction)
        for field, counts in metrics.items():
            combined = totals.setdefault(field, dict.fromkeys(counts, 0))
            for metric, value in counts.items():
                combined[metric] += value
        succeeded += 1

    skipped = len(documents) - succeeded - failed
    print(f"\nУспешно: {succeeded}/{len(documents)}; ошибок: {failed}; не обработано: {skipped}.")
    if not succeeded:
        print("Метрики не рассчитаны: нет успешно обработанных документов.")
        return 1
    print("Метрики только по успешным ответам. Ошибки API не считаются пропусками полей.")
    print(f"{'Поле':<24} {'Верно/всего':>12} {'Точность':>10} {'Галлюцинации':>13} {'Пропуски':>10}")
    for field, counts in totals.items():
        ratio = f"{counts['correct']}/{counts['total']}"
        accuracy = counts["correct"] / counts["total"]
        print(f"{field:<24} {ratio:>12} {accuracy:>9.1%} {counts['hallucinations']:>13} {counts['omissions']:>10}")
    print("Всего галлюцинаций:", sum(c["hallucinations"] for c in totals.values()))
    print("Всего пропусков:", sum(c["omissions"] for c in totals.values()))
    return 1 if failed or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
