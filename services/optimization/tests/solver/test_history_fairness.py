from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from dutyflow_optimizer.contracts import (
    AssignmentOptimizationSnapshot,
    HistorySnapshot,
    OptimizationSettings,
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
        load_points=100,
        eligible_people=[
            PERSON_A,
            PERSON_B,
        ],
    )


def make_snapshot(
    *,
    history_a: HistorySnapshot,
    history_b: HistorySnapshot,
    max_history_correction_percent: int = 30,
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
        settings=OptimizationSettings(
            max_history_correction_percent=(max_history_correction_percent)
        ),
        people=[
            PersonSnapshot(
                id=PERSON_A,
                fairness_weight=1000,
                history=history_a,
            ),
            PersonSnapshot(
                id=PERSON_B,
                fairness_weight=1000,
                history=history_b,
            ),
        ],
        slots=[
            make_slot("slot-1", 0),
            make_slot("slot-2", 2),
            make_slot("slot-3", 4),
            make_slot("slot-4", 6),
        ],
    )


def assignment_counts(
    result,
) -> dict[UUID, int]:
    counts = {
        PERSON_A: 0,
        PERSON_B: 0,
    }

    for assignment in result.assignments:
        counts[assignment.person_id] += 1

    return counts


def test_history_overload_reduces_new_assignments() -> None:
    snapshot = make_snapshot(
        history_a=HistorySnapshot(
            actual_load_points=1000,
            expected_load_points=500,
        ),
        history_b=HistorySnapshot(
            actual_load_points=0,
            expected_load_points=500,
        ),
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 4
    assert result.unfilled_count == 0

    counts = assignment_counts(result)

    assert counts[PERSON_A] == 1
    assert counts[PERSON_B] == 3


def test_history_correction_is_clamped() -> None:
    history_a = HistorySnapshot(
        actual_load_points=10000,
        expected_load_points=0,
    )
    history_b = HistorySnapshot(
        actual_load_points=0,
        expected_load_points=10000,
    )

    clamped_snapshot = make_snapshot(
        history_a=history_a,
        history_b=history_b,
        max_history_correction_percent=30,
    )

    strong_snapshot = make_snapshot(
        history_a=history_a,
        history_b=history_b,
        max_history_correction_percent=100,
    )

    clamped_result = solve_assignment(clamped_snapshot)
    strong_result = solve_assignment(strong_snapshot)

    assert clamped_result.status == "OPTIMAL"
    assert strong_result.status == "OPTIMAL"

    clamped_counts = assignment_counts(clamped_result)
    strong_counts = assignment_counts(strong_result)

    assert clamped_counts[PERSON_A] == 1
    assert clamped_counts[PERSON_B] == 3

    assert strong_counts[PERSON_A] == 0
    assert strong_counts[PERSON_B] == 4


def test_balanced_history_keeps_equal_current_load() -> None:
    snapshot = make_snapshot(
        history_a=HistorySnapshot(
            actual_load_points=500,
            expected_load_points=500,
        ),
        history_b=HistorySnapshot(
            actual_load_points=500,
            expected_load_points=500,
        ),
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"

    counts = assignment_counts(result)

    assert counts[PERSON_A] == 2
    assert counts[PERSON_B] == 2
