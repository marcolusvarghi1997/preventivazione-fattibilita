from dataclasses import dataclass
from apps.quotes.phases import phase_registry


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def can_complete(self) -> bool:
        return not self.errors


def validate_quote(quote) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    items = list(quote.items.all())
    if not items:
        errors.append("Il preventivo deve contenere almeno un articolo.")
    for item in items:
        prefix = f"Articolo {item.code or '(senza codice)'}"
        if not item.code.strip():
            errors.append(f"{prefix}: il codice e obbligatorio.")
        if item.quantity < 1:
            errors.append(f"{prefix}: la quantita deve essere maggiore di zero.")
        materials = list(item.materials.all())
        if not materials:
            errors.append(f"{prefix}: inserire almeno un materiale.")
        for material in materials:
            if material.weight_kg <= 0:
                errors.append(f"{prefix}: il peso del materiale deve essere maggiore di zero.")
            if material.unit_cost_snapshot is None:
                warnings.append(f"{prefix}: costo materiale non valorizzato ({material.material.name}).")
        for phase in item.phases.all():
            config = phase_registry[phase.definition.code]
            errors.extend(f"{prefix} - {message}" for message in config.validate(phase))
            warnings.extend(f"{prefix} - {message}" for message in config.warnings(phase))
    return ValidationResult(errors, warnings)
