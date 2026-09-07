from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from dutyflow_optimizer.contracts import (
    AssignmentOptimizationSnapshot,
    CalendarFlags,
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
    *,
    load_points: int = 100,
    is_weekend: bool = False,
    is_holiday: bool = False,
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
        calendar=CalendarFlags(
            is_weekend=is_weekend,
            is_holiday=is_holiday,
        ),
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
                history=(history_a or HistorySnapshot()),
            ),
            PersonSnapshot(
                id=PERSON_B,
                history=(history_b or HistorySnapshot()),
            ),
        ],
        slots=slots,
    )


def assignment_loads(
    snapshot: AssignmentOptimizationSnapshot,
    result,
    *,
    dimension: str,
) -> dict[UUID, int]:
    slot_by_id = {slot.id: slot for slot in snapshot.slots}

    loads = {
        PERSON_A: 0,
        PERSON_B: 0,
    }

    for assignment in result.assignments:
        slot = slot_by_id[assignment.slot_id]

        if dimension == "weekend" and not slot.calendar.is_weekend:
            continue

        if dimension == "holiday" and not slot.calendar.is_holiday:
            continue

        loads[assignment.person_id] += slot.load_points

    return loads


def test_solver_balances_weekend_load_after_total_load() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot(
                "weekend-1",
                0,
                is_weekend=True,
            ),
            make_slot(
                "weekend-2",
                2,
                is_weekend=True,
            ),
            make_slot("weekday-1", 4),
            make_slot("weekday-2", 6),
            make_slot("weekday-3", 8),
            make_slot("weekday-4", 10),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 6
    assert result.unfilled_count == 0

    weekend_loads = assignment_loads(
        snapshot,
        result,
        dimension="weekend",
    )

    assert weekend_loads[PERSON_A] == 100
    assert weekend_loads[PERSON_B] == 100


def test_weekend_history_shifts_weekend_assignments() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot(
                "weekend-1",
                0,
                load_points=50,
                is_weekend=True,
            ),
            make_slot(
                "weekend-2",
                2,
                load_points=50,
                is_weekend=True,
            ),
            make_slot(
                "weekend-3",
                4,
                load_points=50,
                is_weekend=True,
            ),
            make_slot(
                "weekend-4",
                6,
                load_points=50,
                is_weekend=True,
            ),
            make_slot(
                "weekday-1",
                8,
                load_points=50,
            ),
            make_slot(
                "weekday-2",
                10,
                load_points=50,
            ),
            make_slot(
                "weekday-3",
                12,
                load_points=50,
            ),
            make_slot(
                "weekday-4",
                14,
                load_points=50,
            ),
        ],
        history_a=HistorySnapshot(
            weekend_load_points=100,
            expected_weekend_load_points=0,
        ),
        history_b=HistorySnapshot(
            weekend_load_points=0,
            expected_weekend_load_points=100,
        ),
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 8

    weekend_loads = assignment_loads(
        snapshot,
        result,
        dimension="weekend",
    )

    assert weekend_loads[PERSON_A] == 50
    assert weekend_loads[PERSON_B] == 150


def test_holiday_history_shifts_holiday_assignments() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot(
                "holiday-1",
                0,
                load_points=50,
                is_holiday=True,
            ),
            make_slot(
                "holiday-2",
                2,
                load_points=50,
                is_holiday=True,
            ),
            make_slot(
                "holiday-3",
                4,
                load_points=50,
                is_holiday=True,
            ),
            make_slot(
                "holiday-4",
                6,
                load_points=50,
                is_holiday=True,
            ),
            make_slot(
                "normal-1",
                8,
                load_points=50,
            ),
            make_slot(
                "normal-2",
                10,
                load_points=50,
            ),
            make_slot(
                "normal-3",
                12,
                load_points=50,
            ),
            make_slot(
                "normal-4",
                14,
                load_points=50,
            ),
        ],
        history_a=HistorySnapshot(
            holiday_load_points=100,
            expected_holiday_load_points=0,
        ),
        history_b=HistorySnapshot(
            holiday_load_points=0,
            expected_holiday_load_points=100,
        ),
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.filled_count == 8

    holiday_loads = assignment_loads(
        snapshot,
        result,
        dimension="holiday",
    )

    assert holiday_loads[PERSON_A] == 50
    assert holiday_loads[PERSON_B] == 150
