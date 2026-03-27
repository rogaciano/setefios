from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


@register.filter
def brl(value):
    normalized = _to_decimal(value)
    formatted = f"{normalized:,.2f}"
    return f"R$ {formatted}".replace(",", "_").replace(".", ",").replace("_", ".")
