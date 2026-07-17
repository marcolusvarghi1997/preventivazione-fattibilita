from .base import PhaseConfig


class TreatmentConfig(PhaseConfig):
    def validate(self, phase) -> list[str]:
        if not phase.active:
            return []
        errors = []
        for treatment in phase.treatments.all():
            if treatment.treatment_type == treatment.TreatmentType.OTHER and not treatment.description.strip():
                errors.append("Trattamento Esterno: la descrizione e obbligatoria per il tipo Altro.")
        return errors


CONFIG = TreatmentConfig("trattamento-esterno", "Trattamento Esterno", 11, "treatment", multiple_rows=True)
