"""Схема результата из задания А. Все поля обязательны, часть допускает null."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Confidence = Annotated[Number, Field(ge=0, le=1)]


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    qty: Number | None
    price: Number | None


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    doc_type: Literal["invoice", "commercial_offer", "act", "unknown"]
    supplier_name: str | None
    supplier_bin: Annotated[str, Field(pattern=r"^[0-9]{12}$")] | None
    doc_number: str | None
    doc_date: Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")] | None
    currency: Literal["KZT", "USD", "EUR"] | None
    total_amount: Number | None
    vat_amount: Number | None
    line_items: list[LineItem]
    field_confidence: dict[str, Confidence]
    warnings: list[str]

    @field_validator("doc_date")
    @classmethod
    def check_date(cls, value: str | None) -> str | None:
        if value is not None:
            date.fromisoformat(value)
        return value
