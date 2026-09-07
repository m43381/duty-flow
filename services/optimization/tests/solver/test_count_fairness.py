from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from dutyflow_optimizer.contracts import (
    AssignmentOptimizationSnapshot,
    HistorySnapshot,
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
    history_a: HistorySnapshot | None = None,
    history_b: HistorySnapshot | None = None,
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
                history=history_a or HistorySnapshot(),
            ),
            PersonSnapshot(
                id=PERSON_B,
                history=history_b or HistorySnapshot(),
            ),
        ],
        slots=slots,
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


def assignment_loads(
    snapshot: AssignmentOptimizationSnapshot,
    result,
) -> dict[UUID, int]:
    slot_loads = {slot.id: slot.load_points for slot in snapshot.slots}

    loads = {
        PERSON_A: 0,
        PERSON_B: 0,
    }

    for assignment in result.assignments:
        loads[assignment.person_id] += slot_loads[assignment.slot_id]

    return loads


def test_count_fairness_breaks_total_load_tie() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot("heavy", 0, 300),
            make_slot("medium", 2, 200),
            make_slot("light-1", 4, 100),
            make_slot("light-2", 6, 100),
            make_slot("light-3", 8, 100),
            make_slot("light-4", 10, 100),
            make_slot("light-5", 12, 100),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 7
    assert result.unfilled_count == 0

    loads = assignment_loads(
        snapshot,
        result,
    )
    counts = assignment_counts(result)

    # Общая weighted load важнее количества:
    # сначала достигаем идеальных 500/500 points.
    assert loads[PERSON_A] == 500
    assert loads[PERSON_B] == 500

    # Среди нескольких решений 500/500 выбирается
    # более ровное количество 3/4, а не 2/5.
    assert sorted(counts.values()) == [3, 4]


def test_count_history_shifts_count_without_hurting_load_balance() -> None:
    slots = [
        make_slot("heavy-1", 0, 300),
        make_slot("heavy-2", 2, 300),
        make_slot("medium-1", 4, 200),
        make_slot("medium-2", 6, 200),
    ]

    for index in range(10):
        slots.append(
            make_slot(
                f"light-{index + 1}",
                8 + index * 2,
                100,
            )
        )

    snapshot = make_snapshot(
        slots=slots,
        history_a=HistorySnapshot(
            duty_count=20,
            expected_duty_count=0,
        ),
        history_b=HistorySnapshot(
            duty_count=0,
            expected_duty_count=20,
        ),
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 14
    assert result.unfilled_count == 0

    loads = assignment_loads(
        snapshot,
        result,
    )
    counts = assignment_counts(result)

    # История количества не имеет права ломать
    # основной баланс weighted load.
    assert loads[PERSON_A] == 1000
    assert loads[PERSON_B] == 1000

    # При 30% history correction цель по количеству
    # сдвигается примерно к 5/9.
    assert counts[PERSON_A] == 5
    assert counts[PERSON_B] == 9
