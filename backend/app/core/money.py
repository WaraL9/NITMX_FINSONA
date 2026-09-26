"""Money helpers. All money in Finsona is Decimal, never float."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SATANG = Decimal("0.01")


class MoneyError(ValueError):
    pass


def to_money(value: str | int | float | Decimal) -> Decimal:
    """Parse a THB amount into a 2-dp Decimal.

    Accepts statement-style strings: "1,200,000.00", "(450,000.00)", "450,000.00-",
    "-3,800,000", "฿ 1,000". Floats go through str() so 0.1 stays 0.10.
    """
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        d = Decimal(str(value))
    else:
        s = value.strip().replace(",", "").replace("฿", "").replace("THB", "").replace(" ", "")
        negative = False
        if s.startswith("(") and s.endswith(")"):
            negative, s = True, s[1:-1]
        if s.endswith("-"):
            negative, s = True, s[:-1]
        if not s:
            raise MoneyError(f"empty amount: {value!r}")
        try:
            d = Decimal(s)
        except InvalidOperation as e:
            raise MoneyError(f"not an amount: {value!r}") from e
        if negative:
            d = -d
    return d.quantize(SATANG, rounding=ROUND_HALF_UP)


def fmt_thb(amount: Decimal, decimals: int = 2) -> str:
    """Format as '1,200,000.00' (or without decimals when decimals=0)."""
    q = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    return f"{amount.quantize(q, rounding=ROUND_HALF_UP):,}"
