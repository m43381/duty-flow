from typing import Literal
from uuid import UUID

from pydantic import Field

from dutyflow_optimizer.contracts.assignment import ContractModel

SolverStatus = Literal[
    "OPTIMAL",
    "FEASIBLE",
    "INFEASIBLE",
    "MODEL_INVALID",
    "UNKNOWN",
]


class AssignmentDecision(ContractModel):
    slot_id: str = Field(min_length=1)
    person_id: UUID


class AssignmentOptimizationResult(ContractModel):
    status: SolverStatus

    assignments: list[AssignmentDecision] = Field(
        default_factory=list,
    )

    unfilled_slots: list[str] = Field(
        default_factory=list,
    )

    filled_count: int = Field(ge=0)
    unfilled_count: int = Field(ge=0)
