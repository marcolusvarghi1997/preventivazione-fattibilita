from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseConfig:
    code: str
    name: str
    order: int
    mode: str
    resource_names: tuple[str, ...] = ()
    multiple_rows: bool = False
    requires_selectable_resource: bool = False

    def validate(self, phase) -> list[str]:
        errors: list[str] = []
        if not phase.active:
            return errors
        if self.mode == "time":
            if not phase.operations.exists():
                errors.append(f"{self.name}: inserire almeno un tempo di lavorazione o attrezzaggio.")
            for operation in phase.operations.all():
                if operation.working_minutes == 0 and operation.setup_minutes == 0:
                    errors.append(f"{self.name}: indicare un tempo maggiore di zero.")
                if operation.resource.phase_id != phase.definition_id:
                    errors.append(f"{self.name}: la risorsa scelta non appartiene a questa fase.")
        return errors

    def warnings(self, phase) -> list[str]:
        if not phase.active:
            return []
        return [
            f"{self.name}: costo orario della risorsa '{op.resource_name_snapshot}' non configurato."
            for op in phase.operations.all() if op.hourly_cost_snapshot == 0
        ]
