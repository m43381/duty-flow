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

    @model_validator(mode="after")
    def validate_references(self) -> AssignmentOptimizationSnapshot:
        person_ids = [person.id for person in self.people]

        if len(person_ids) != len(set(person_ids)):
            raise ValueError("people must contain unique ids")

        slot_ids = [slot.id for slot in self.slots]

        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("slots must contain unique ids")

        known_people = set(person_ids)

        for slot in self.slots:
            unknown_people = set(slot.eligible_people) - known_people

            if unknown_people:
                unknown = ", ".join(sorted(str(person_id) for person_id in unknown_people))

                raise ValueError(f"slot {slot.id} references unknown eligible people: {unknown}")

        return self
