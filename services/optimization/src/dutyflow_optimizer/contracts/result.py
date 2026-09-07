from typing import Literal
from uuid import UUID

from pydantic import Field

from dutyflow_optimizer.contracts.assignment import (
    ContractModel,
    NonNegativeInt,
)

SolverStatus = Literal[
    "OPTIMAL",
    "FEASIBLE",
    "INFEASIBLE",
    "MODEL_INVALID",
    "UNKNOWN",
]

UnfilledReasonCode = Literal[
    "NO_ELIGIBLE_PEOPLE",
    "REST_CONSTRAINT",
    "MANUAL_FORBID",
    "CAPACITY_SHORTAGE",
    "UNKNOWN",
]


class AssignmentDecision(ContractModel):
    slot_id: str = Field(min_length=1)
    person_id: UUID


class UnfilledSlotDetail(ContractModel):
    slot_id: str = Field(min_length=1)
    reason_code: UnfilledReasonCode

    eligible_count: NonNegativeInt = 0

    # Причины, которые уже посчитал Scheduling Service
    # при построении списка eligible_people.
    exclusion_summary: dict[str, NonNegativeInt] = Field(
        default_factory=dict,
    )

    # Причины, которые обнаружены уже внутри optimizer.
    blocking_summary: dict[str, NonNegativeInt] = Field(
        default_factory=dict,
    )


class PersonAssignmentMetrics(ContractModel):
    person_id: UUID

    assignment_count: NonNegativeInt = 0
    load_points: NonNegativeInt = 0

    weekend_load_points: NonNegativeInt = 0
    holiday_load_points: NonNegativeInt = 0


class AssignmentMetrics(ContractModel):
    total_slots: NonNegativeInt
    filled_count: NonNegativeInt
    unfilled_count: NonNegativeInt

    coverage_percent: float = Field(
        ge=0,
        le=100,
    )

    assigned_load_points: NonNegativeInt = 0
    weekend_load_points: NonNegativeInt = 0
    holiday_load_points: NonNegativeInt = 0

    people: list[PersonAssignmentMetrics] = Field(
        default_factory=list,
    )


class AssignmentOptimizationResult(ContractModel):
    status: SolverStatus

    assignments: list[AssignmentDecision] = Field(
        default_factory=list,
    )

    # Оставляем старое поле для простых клиентов и обратной совместимости.
    unfilled_slots: list[str] = Field(
        default_factory=list,
    )

    # Структурированный preview для UI/API.
    unfilled_details: list[UnfilledSlotDetail] = Field(
        default_factory=list,
    )

    filled_count: NonNegativeInt
    unfilled_count: NonNegativeInt

    metrics: AssignmentMetrics | None = None
