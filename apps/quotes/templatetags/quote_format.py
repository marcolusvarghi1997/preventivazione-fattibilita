from django import template

from apps.quotes.formatting import format_decimal_it, format_money, format_weight

register = template.Library()


@register.filter
def decimal_it(value, places=2):
    try:
        return format_decimal_it(value, int(places))
    except (TypeError, ValueError):
        return "—"


@register.filter
def money(value):
    try:
        return format_money(value)
    except (TypeError, ValueError):
        return "—"


@register.filter
def weight(value):
    try:
        return format_weight(value)
    except (TypeError, ValueError):
        return "—"
