from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from dutyflow_optimizer.contracts import (
    AssignmentOptimizationSnapshot,
    PeriodSnapshot,
    PersonSnapshot,
    PositionSlotSnapshot,
)
from dutyflow_optimizer.solver import solve_assignment

PERSON_A = UUID("20000000-0000-0000-0000-000000000001")
PERSON_B = UUID("20000000-0000-0000-0000-000000000002")


def make_slot(
    slot_id: str,
    day_offset: int,
    load_points: int,
) -> PositionSlotSnapshot:
    starts_at = datetime(
        2027,
        10,
        1,
        8,
        tzinfo=UTC,
    ) + timedelta(days=day_offset)

    return PositionSlotSnapshot(
        id=slot_id,
        occurrence_id=uuid4(),
        duty_type_id=uuid4(),
        position_id=uuid4(),
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=24),
        rest_minutes=0,
        load_points=load_points,
        eligible_people=[
            PERSON_A,
            PERSON_B,
        ],
    )


def make_snapshot(
    slots: list[PositionSlotSnapshot],
    *,
    weight_a: int = 1000,
    weight_b: int = 1000,
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
            PersonSnapshot(
                id=PERSON_A,
                fairness_weight=weight_a,
            ),
            PersonSnapshot(
                id=PERSON_B,
                fairness_weight=weight_b,
            ),
        ],
        slots=slots,
    )


def assignment_counts(
    snapshot_result,
) -> dict[UUID, int]:
    counts = {
        PERSON_A: 0,
        PERSON_B: 0,
    }

    for assignment in snapshot_result.assignments:
        counts[assignment.person_id] += 1

    return counts


def assignment_loads(
    snapshot: AssignmentOptimizationSnapshot,
    snapshot_result,
) -> dict[UUID, int]:
    slot_loads = {slot.id: slot.load_points for slot in snapshot.slots}

    loads = {
        PERSON_A: 0,
        PERSON_B: 0,
    }

    for assignment in snapshot_result.assignments:
        loads[assignment.person_id] += slot_loads[assignment.slot_id]

    return loads


def test_solver_balances_equal_load_between_equal_people() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot("slot-1", 0, 100),
            make_slot("slot-2", 2, 100),
            make_slot("slot-3", 4, 100),
            make_slot("slot-4", 6, 100),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 4
    assert result.unfilled_count == 0

    counts = assignment_counts(result)

    assert counts[PERSON_A] == 2
    assert counts[PERSON_B] == 2


def test_solver_balances_load_points_not_duty_count() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot("heavy", 0, 300),
            make_slot("light-1", 2, 100),
            make_slot("light-2", 4, 100),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 3

    counts = assignment_counts(result)
    loads = assignment_loads(
        snapshot,
        result,
    )

    assert sorted(counts.values()) == [1, 2]
    assert sorted(loads.values()) == [200, 300]


def test_solver_respects_fairness_weight() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot("slot-1", 0, 100),
            make_slot("slot-2", 2, 100),
            make_slot("slot-3", 4, 100),
        ],
        weight_a=500,
        weight_b=1000,
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 3

    counts = assignment_counts(result)

    assert counts[PERSON_A] == 1
    assert counts[PERSON_B] == 2
