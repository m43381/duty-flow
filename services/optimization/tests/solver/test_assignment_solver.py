from datetime import UTC, datetime
from uuid import UUID, uuid4

from dutyflow_optimizer.contracts import (
    AssignmentOptimizationSnapshot,
    ExistingAssignmentSnapshot,
    ManualConstraint,
    PeriodSnapshot,
    PersonSnapshot,
    PositionSlotSnapshot,
)
from dutyflow_optimizer.solver import solve_assignment

PERSON_A = UUID("20000000-0000-0000-0000-000000000001")

PERSON_B = UUID("20000000-0000-0000-0000-000000000002")


def make_snapshot(
    eligible_people: list[UUID],
    *,
    existing_assignments: (list[ExistingAssignmentSnapshot] | None) = None,
    manual_constraints: (list[ManualConstraint] | None) = None,
) -> AssignmentOptimizationSnapshot:
    return AssignmentOptimizationSnapshot(
        run_id=uuid4(),
        unit_id=uuid4(),
        period=PeriodSnapshot(
            starts_at=datetime(
                2027,
                10,
                1,
                tzinfo=UTC,
            ),
            ends_at=datetime(
                2027,
                11,
                1,
                tzinfo=UTC,
            ),
        ),
        people=[
            PersonSnapshot(id=PERSON_A),
            PersonSnapshot(id=PERSON_B),
        ],
        slots=[
            PositionSlotSnapshot(
                id="slot-1",
                occurrence_id=uuid4(),
                duty_type_id=uuid4(),
                position_id=uuid4(),
                starts_at=datetime(
                    2027,
                    10,
                    10,
                    18,
                    tzinfo=UTC,
                ),
                ends_at=datetime(
                    2027,
                    10,
                    11,
                    18,
                    tzinfo=UTC,
                ),
                load_points=100,
                eligible_people=eligible_people,
            )
        ],
        existing_assignments=(existing_assignments or []),
        manual_constraints=(manual_constraints or []),
    )


def test_solver_fills_slot_when_candidate_exists() -> None:
    snapshot = make_snapshot(
        eligible_people=[PERSON_A],
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 1
    assert result.unfilled_count == 0

    assert result.assignments[0].person_id == PERSON_A


def test_solver_returns_unfilled_when_no_candidate_exists() -> None:
    snapshot = make_snapshot(
        eligible_people=[],
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 0
    assert result.unfilled_count == 1
    assert result.unfilled_slots == ["slot-1"]


def test_solver_respects_forbid() -> None:
    snapshot = make_snapshot(
        eligible_people=[
            PERSON_A,
            PERSON_B,
        ],
        manual_constraints=[
            ManualConstraint(
                type="FORBID",
                slot_id="slot-1",
                person_id=PERSON_A,
            )
        ],
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.assignments[0].person_id == PERSON_B


def test_solver_respects_force() -> None:
    snapshot = make_snapshot(
        eligible_people=[
            PERSON_A,
            PERSON_B,
        ],
        manual_constraints=[
            ManualConstraint(
                type="FORCE",
                slot_id="slot-1",
                person_id=PERSON_B,
            )
        ],
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.assignments[0].person_id == PERSON_B


def test_solver_preserves_locked_assignment() -> None:
    snapshot = make_snapshot(
        eligible_people=[
            PERSON_A,
            PERSON_B,
        ],
        existing_assignments=[
            ExistingAssignmentSnapshot(
                assignment_id=uuid4(),
                slot_id="slot-1",
                person_id=PERSON_A,
                source="MANUAL",
                locked=True,
            )
        ],
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.assignments[0].person_id == PERSON_A


def test_conflicting_lock_and_force_is_infeasible() -> None:
    snapshot = make_snapshot(
        eligible_people=[
            PERSON_A,
            PERSON_B,
        ],
        existing_assignments=[
            ExistingAssignmentSnapshot(
                assignment_id=uuid4(),
                slot_id="slot-1",
                person_id=PERSON_A,
                source="MANUAL",
                locked=True,
            )
        ],
        manual_constraints=[
            ManualConstraint(
                type="FORCE",
                slot_id="slot-1",
                person_id=PERSON_B,
            )
        ],
    )

    result = solve_assignment(snapshot)

    assert result.status == "INFEASIBLE"
