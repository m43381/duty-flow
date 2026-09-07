from datetime import UTC, datetime
from uuid import UUID, uuid4

from dutyflow_optimizer.contracts import (
    AssignmentOptimizationSnapshot,
    ExistingAssignmentSnapshot,
    ManualConstraint,
    PeriodSnapshot,
    PersonSnapshot,
    PositionSlotSnapshot,
    PreviousExecutionSnapshot,
)
from dutyflow_optimizer.solver import solve_assignment

PERSON_A = UUID("20000000-0000-0000-0000-000000000001")
PERSON_B = UUID("20000000-0000-0000-0000-000000000002")


def make_slot(
    slot_id: str,
    *,
    starts_at: datetime,
    ends_at: datetime,
    eligible_people: list[UUID],
    rest_minutes: int = 0,
) -> PositionSlotSnapshot:
    return PositionSlotSnapshot(
        id=slot_id,
        occurrence_id=uuid4(),
        duty_type_id=uuid4(),
        position_id=uuid4(),
        starts_at=starts_at,
        ends_at=ends_at,
        rest_minutes=rest_minutes,
        load_points=100,
        eligible_people=eligible_people,
    )


def make_snapshot_with_slots(
    slots: list[PositionSlotSnapshot],
    *,
    previous_executions: list[PreviousExecutionSnapshot] | None = None,
) -> AssignmentOptimizationSnapshot:
    return AssignmentOptimizationSnapshot(
        run_id=uuid4(),
        unit_id=uuid4(),
        period=PeriodSnapshot(
            starts_at=datetime(2027, 10, 1, tzinfo=UTC),
            ends_at=datetime(2027, 11, 1, tzinfo=UTC),
        ),
        people=[
            PersonSnapshot(id=PERSON_A),
            PersonSnapshot(id=PERSON_B),
        ],
        slots=slots,
        previous_executions=previous_executions or [],
    )


def make_snapshot(
    eligible_people: list[UUID],
    *,
    existing_assignments: list[ExistingAssignmentSnapshot] | None = None,
    manual_constraints: list[ManualConstraint] | None = None,
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


def test_solver_does_not_assign_same_person_to_overlapping_slots() -> None:
    snapshot = make_snapshot_with_slots(
        slots=[
            make_slot(
                "slot-1",
                starts_at=datetime(2027, 10, 10, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 11, 18, tzinfo=UTC),
                eligible_people=[PERSON_A],
            ),
            make_slot(
                "slot-2",
                starts_at=datetime(2027, 10, 11, 12, tzinfo=UTC),
                ends_at=datetime(2027, 10, 12, 12, tzinfo=UTC),
                eligible_people=[PERSON_A],
            ),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 1
    assert result.unfilled_count == 1


def test_solver_respects_rest_between_slots() -> None:
    snapshot = make_snapshot_with_slots(
        slots=[
            make_slot(
                "slot-1",
                starts_at=datetime(2027, 10, 10, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 11, 18, tzinfo=UTC),
                rest_minutes=1440,
                eligible_people=[PERSON_A],
            ),
            make_slot(
                "slot-2",
                starts_at=datetime(2027, 10, 12, 10, tzinfo=UTC),
                ends_at=datetime(2027, 10, 13, 10, tzinfo=UTC),
                eligible_people=[PERSON_A],
            ),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 1
    assert result.unfilled_count == 1


def test_solver_allows_assignment_when_rest_is_exactly_completed() -> None:
    snapshot = make_snapshot_with_slots(
        slots=[
            make_slot(
                "slot-1",
                starts_at=datetime(2027, 10, 10, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 11, 18, tzinfo=UTC),
                rest_minutes=1440,
                eligible_people=[PERSON_A],
            ),
            make_slot(
                "slot-2",
                starts_at=datetime(2027, 10, 12, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 13, 18, tzinfo=UTC),
                eligible_people=[PERSON_A],
            ),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 2
    assert result.unfilled_count == 0


def test_solver_uses_another_person_when_first_person_has_rest_conflict() -> None:
    snapshot = make_snapshot_with_slots(
        slots=[
            make_slot(
                "slot-1",
                starts_at=datetime(2027, 10, 10, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 11, 18, tzinfo=UTC),
                rest_minutes=1440,
                eligible_people=[PERSON_A],
            ),
            make_slot(
                "slot-2",
                starts_at=datetime(2027, 10, 12, 10, tzinfo=UTC),
                ends_at=datetime(2027, 10, 13, 10, tzinfo=UTC),
                eligible_people=[
                    PERSON_A,
                    PERSON_B,
                ],
            ),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 2
    assert result.unfilled_count == 0

    assignments = {assignment.slot_id: assignment.person_id for assignment in result.assignments}

    assert assignments["slot-1"] == PERSON_A
    assert assignments["slot-2"] == PERSON_B


def test_previous_execution_blocks_assignment_during_rest() -> None:
    snapshot = make_snapshot_with_slots(
        slots=[
            make_slot(
                "slot-1",
                starts_at=datetime(2027, 10, 2, 10, tzinfo=UTC),
                ends_at=datetime(2027, 10, 3, 10, tzinfo=UTC),
                eligible_people=[
                    PERSON_A,
                    PERSON_B,
                ],
            )
        ],
        previous_executions=[
            PreviousExecutionSnapshot(
                execution_id=uuid4(),
                person_id=PERSON_A,
                starts_at=datetime(2027, 9, 30, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 1, 18, tzinfo=UTC),
                rest_minutes=1440,
            )
        ],
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 1
    assert result.assignments[0].person_id == PERSON_B


def test_previous_execution_allows_assignment_after_rest_completed() -> None:
    snapshot = make_snapshot_with_slots(
        slots=[
            make_slot(
                "slot-1",
                starts_at=datetime(2027, 10, 2, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 3, 18, tzinfo=UTC),
                eligible_people=[PERSON_A],
            )
        ],
        previous_executions=[
            PreviousExecutionSnapshot(
                execution_id=uuid4(),
                person_id=PERSON_A,
                starts_at=datetime(2027, 9, 30, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 1, 18, tzinfo=UTC),
                rest_minutes=1440,
            )
        ],
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 1
    assert result.unfilled_count == 0
    assert result.assignments[0].person_id == PERSON_A
