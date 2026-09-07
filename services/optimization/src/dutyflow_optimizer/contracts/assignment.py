from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

NonNegativeInt = Annotated[int, Field(ge=0)]


class ContractModel(BaseModel):
    """Base model for optimizer contracts."""

    model_config = ConfigDict(extra="forbid")


class PeriodSnapshot(ContractModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def validate_period(self) -> PeriodSnapshot:
        if self.ends_at <= self.starts_at:
            raise ValueError("period ends_at must be later than starts_at")

        return self


class HistorySnapshot(ContractModel):
    actual_load_points: NonNegativeInt = 0
    expected_load_points: NonNegativeInt = 0

    weekend_load_points: NonNegativeInt = 0
    expected_weekend_load_points: NonNegativeInt = 0

    holiday_load_points: NonNegativeInt = 0
    expected_holiday_load_points: NonNegativeInt = 0

    duty_count: NonNegativeInt = 0
    expected_duty_count: NonNegativeInt = 0


class PersonSnapshot(ContractModel):
    id: UUID

    fairness_weight: int = Field(
        default=1000,
        ge=0,
        le=1000,
    )

    history: HistorySnapshot = Field(
        default_factory=HistorySnapshot,
    )

    unavailable_until: AwareDatetime | None = None


class CalendarFlags(ContractModel):
    is_weekend: bool = False
    is_holiday: bool = False


class PositionSlotSnapshot(ContractModel):
    id: str = Field(min_length=1)

    occurrence_id: UUID
    duty_type_id: UUID
    position_id: UUID

    starts_at: AwareDatetime
    ends_at: AwareDatetime

    rest_minutes: NonNegativeInt = 0
    load_points: NonNegativeInt

    calendar: CalendarFlags = Field(
        default_factory=CalendarFlags,
    )

    eligible_people: list[UUID] = Field(
        default_factory=list,
    )

    exclusion_summary: dict[str, NonNegativeInt] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_slot(self) -> PositionSlotSnapshot:
        if self.ends_at <= self.starts_at:
            raise ValueError("slot ends_at must be later than starts_at")

        if len(self.eligible_people) != len(set(self.eligible_people)):
            raise ValueError("eligible_people must not contain duplicates")

        return self


class OptimizationSettings(ContractModel):
    profile: Literal["BALANCED"] = "BALANCED"

    time_limit_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
    )

    history_days: int = Field(
        default=90,
        ge=0,
    )

    load_scale: int = Field(
        default=100,
        ge=1,
    )

    max_history_correction_percent: int = Field(
        default=30,
        ge=0,
        le=100,
    )


class ExistingAssignmentSnapshot(ContractModel):
    assignment_id: UUID
    slot_id: str = Field(min_length=1)
    person_id: UUID

    source: Literal["AUTO", "MANUAL", "IMPORT"]

    locked: bool = False
    published: bool = False


class ManualConstraint(ContractModel):
    type: Literal["FORCE", "FORBID"]

    slot_id: str = Field(min_length=1)
    person_id: UUID

    reason: str | None = None


class PreviousExecutionSnapshot(ContractModel):
    execution_id: UUID
    person_id: UUID

    starts_at: AwareDatetime
    ends_at: AwareDatetime

    rest_minutes: NonNegativeInt = 0

    @model_validator(mode="after")
    def validate_execution(self) -> PreviousExecutionSnapshot:
        if self.ends_at <= self.starts_at:
            raise ValueError("previous execution ends_at must be later than starts_at")

        return self


class AssignmentOptimizationSnapshot(ContractModel):
    schema_version: Literal["1.0"] = "1.0"

    run_id: UUID
    unit_id: UUID

    period: PeriodSnapshot

    settings: OptimizationSettings = Field(
        default_factory=OptimizationSettings,
    )

    people: list[PersonSnapshot]
    slots: list[PositionSlotSnapshot]

    existing_assignments: list[ExistingAssignmentSnapshot] = Field(
        default_factory=list,
    )

    manual_constraints: list[ManualConstraint] = Field(
        default_factory=list,
    )

    previous_executions: list[PreviousExecutionSnapshot] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_references(self) -> AssignmentOptimizationSnapshot:
        person_ids = [person.id for person in self.people]

        if len(person_ids) != len(set(person_ids)):
            raise ValueError("people must contain unique ids")

        slot_ids = [slot.id for slot in self.slots]

        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("slots must contain unique ids")

        known_people = set(person_ids)
        known_slots = set(slot_ids)

        for slot in self.slots:
            unknown_people = set(slot.eligible_people) - known_people

            if unknown_people:
                unknown = ", ".join(sorted(str(person_id) for person_id in unknown_people))

                raise ValueError(f"slot {slot.id} references unknown eligible people: {unknown}")

        assignment_ids = [assignment.assignment_id for assignment in self.existing_assignments]

        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("existing_assignments must contain unique assignment ids")

        assignment_slots = [assignment.slot_id for assignment in self.existing_assignments]

        if len(assignment_slots) != len(set(assignment_slots)):
            raise ValueError("existing_assignments must contain at most one assignment per slot")

        for assignment in self.existing_assignments:
            if assignment.person_id not in known_people:
                raise ValueError(
                    f"existing assignment {assignment.assignment_id} references unknown person"
                )

            if assignment.slot_id not in known_slots:
                raise ValueError(
                    f"existing assignment {assignment.assignment_id} references unknown slot"
                )

            slot = next(slot for slot in self.slots if slot.id == assignment.slot_id)

            if assignment.person_id not in slot.eligible_people:
                raise ValueError(
                    f"existing assignment {assignment.assignment_id} "
                    "references person who is not eligible for its slot"
                )

        forced_slots: set[str] = set()
        constraint_pairs: set[tuple[str, UUID, str]] = set()

        for constraint in self.manual_constraints:
            if constraint.person_id not in known_people:
                raise ValueError("manual constraint references unknown person")

            if constraint.slot_id not in known_slots:
                raise ValueError("manual constraint references unknown slot")

            pair = (
                constraint.slot_id,
                constraint.person_id,
                constraint.type,
            )

            if pair in constraint_pairs:
                raise ValueError("manual_constraints must not contain duplicates")

            constraint_pairs.add(pair)

            opposite_type = "FORBID" if constraint.type == "FORCE" else "FORCE"

            opposite_pair = (
                constraint.slot_id,
                constraint.person_id,
                opposite_type,
            )

            if opposite_pair in constraint_pairs:
                raise ValueError("the same person and slot cannot be both FORCE and FORBID")

            if constraint.type == "FORCE":
                if constraint.slot_id in forced_slots:
                    raise ValueError("a slot cannot have more than one FORCE constraint")

                forced_slots.add(constraint.slot_id)

                slot = next(slot for slot in self.slots if slot.id == constraint.slot_id)

                if constraint.person_id not in slot.eligible_people:
                    raise ValueError(
                        "FORCE constraint references person who is not eligible for its slot"
                    )

        execution_ids = [execution.execution_id for execution in self.previous_executions]

        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("previous_executions must contain unique execution ids")

        for execution in self.previous_executions:
            if execution.person_id not in known_people:
                raise ValueError("previous execution references unknown person")

            if execution.starts_at >= self.period.starts_at:
                raise ValueError("previous execution must start before planning period")

        return self
