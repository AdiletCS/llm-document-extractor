"""CLI: python main.py путь_к_документу.txt"""

import argparse
import sys
from pathlib import Path

from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError
from pydantic import ValidationError

from extractor import extract_document
from validators import validate_document


def main() -> int:
    parser = argparse.ArgumentParser(description="Извлечение данных из TXT в JSON")
    parser.add_argument("document", type=Path, help="TXT-документ в UTF-8")
    args = parser.parse_args()
    try:
        if args.document.suffix.lower() != ".txt":
            raise ValueError("Передайте файл с расширением .txt.")
        text = args.document.read_text(encoding="utf-8-sig")
        if not text.strip():
            raise ValueError("Документ пуст.")
    except FileNotFoundError:
        print("Ошибка: Файл не найден. Проверьте путь.", file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print("Ошибка: Не удалось прочитать файл в UTF-8.", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    try:
        result = validate_document(text, extract_document(text))
    except ValidationError:
        message = "Ответ модели не прошёл проверку схемы. Результат не выдан."
    except AuthenticationError:
        message = "API отклонил ключ. Проверьте OPENAI_API_KEY."
    except RateLimitError:
        message = "Лимит API или квота исчерпаны. Проверьте баланс и лимиты."
    except APIConnectionError:
        message = "Нет соединения с OpenAI API или истекло время ожидания."
    except APIError:
        message = "Ошибка OpenAI API. Результат не получен."
    except OSError:
        message = "Не удалось загрузить настройки или сертификаты для OpenAI API."
    except ValueError as error:
        message = str(error)
    else:
        print(result.model_dump_json(indent=2))
        return 0
    print(f"Ошибка: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
