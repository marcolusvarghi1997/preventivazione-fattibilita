from .base import PhaseConfig


class ExternalPurchaseConfig(PhaseConfig):
    def validate(self, phase) -> list[str]:
        if not phase.active:
            return []
        if not phase.direct_costs.filter(amount__gt=0).exists():
            return ["Acquisti Esterni: inserire almeno un costo esterno di acquisto maggiore di zero."]
        return []

    def warnings(self, phase) -> list[str]:
        return []


CONFIG = ExternalPurchaseConfig("acquisti-esterni", "Acquisti Esterni", 10, "purchase", multiple_rows=True)
