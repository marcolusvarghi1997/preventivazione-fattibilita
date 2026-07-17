from decimal import Decimal

SIXTY = Decimal("60")


def calculate_time_cost(
    *, working_minutes: Decimal, setup_minutes: Decimal, hourly_cost: Decimal,
    operators: int, quantity: int, per_piece: bool,
) -> Decimal:
    """Calcola senza arrotondare: il formato a due decimali appartiene alla presentazione."""
    work = (working_minutes / SIXTY) * hourly_cost * operators
    if per_piece:
        work *= quantity
    setup = (setup_minutes / SIXTY) * hourly_cost * operators
    return work + setup
