from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def normalize_decimal_input(value) -> str:
    """Normalizza un numero scritto con convenzioni italiane o internazionali."""
    if isinstance(value, Decimal):
        return str(value)
    if value is None:
        return ""

    normalized = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not normalized:
        return ""

    comma = normalized.rfind(",")
    point = normalized.rfind(".")
    if comma >= 0 and point >= 0:
        decimal_separator = "," if comma > point else "."
        thousands_separator = "." if decimal_separator == "," else ","
        normalized = normalized.replace(thousands_separator, "")
        normalized = normalized.replace(decimal_separator, ".")
    elif comma >= 0:
        normalized = normalized.replace(",", ".")

    return normalized


def as_decimal(value) -> Decimal:
    try:
        return Decimal(normalize_decimal_input(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Numero non valido") from exc


def format_decimal_it(value, places: int = 2) -> str:
    if value in (None, ""):
        return "—"
    decimal_value = as_decimal(value)
    quantum = Decimal("1").scaleb(-places)
    return format(decimal_value.quantize(quantum, rounding=ROUND_HALF_UP), f".{places}f").replace(".", ",")


def format_money(value) -> str:
    return "—" if value in (None, "") else f"€ {format_decimal_it(value, 2)}"


def format_weight(value) -> str:
    return "—" if value in (None, "") else f"{format_decimal_it(value, 3)} kg"
