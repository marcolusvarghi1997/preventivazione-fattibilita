from .base import PhaseConfig


class ExternalPurchaseConfig(PhaseConfig):
    def validate(self, phase) -> list[str]:
        if not phase.active:
            return []
        if phase.internal_answer == phase.InternalAnswer.NO and not phase.direct_costs.filter(amount__gt=0).exists():
            return ["Acquisti Esterni: se non e realizzabile internamente occorre inserire un costo esterno maggiore di zero."]
        return []

    def warnings(self, phase) -> list[str]:
        if phase.active and phase.internal_answer == phase.InternalAnswer.TO_CHECK:
            return ["Acquisti Esterni: verificare se l'articolo e realizzabile internamente."]
        return []


CONFIG = ExternalPurchaseConfig("acquisti-esterni", "Acquisti Esterni", 10, "purchase", multiple_rows=True)
