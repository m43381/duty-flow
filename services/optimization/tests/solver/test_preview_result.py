from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from dutyflow_optimizer.contracts import (
    AssignmentOptimizationSnapshot,
    CalendarFlags,
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
    day_offset: int,
    *,
    eligible_people: list[UUID],
    load_points: int = 100,
    is_weekend: bool = False,
    is_holiday: bool = False,
    exclusion_summary: dict[str, int] | None = None,
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
        eligible_people=eligible_people,
        exclusion_summary=exclusion_summary or {},
    )


def make_snapshot(
    slots: list[PositionSlotSnapshot],
    *,
    manual_constraints: list[ManualConstraint] | None = None,
    previous_executions: list[PreviousExecutionSnapshot] | None = None,
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
        slots=slots,
        manual_constraints=manual_constraints or [],
        previous_executions=previous_executions or [],
    )


def test_preview_explains_no_eligible_people() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot(
                "slot-1",
                0,
                eligible_people=[],
                exclusion_summary={
                    "ATTRIBUTE_MISMATCH": 2,
                },
            )
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.unfilled_count == 1

    detail = result.unfilled_details[0]

    assert detail.slot_id == "slot-1"
    assert detail.reason_code == "NO_ELIGIBLE_PEOPLE"
    assert detail.eligible_count == 0
    assert detail.exclusion_summary == {
        "ATTRIBUTE_MISMATCH": 2,
    }

    assert result.metrics is not None
    assert result.metrics.coverage_percent == 0.0


def test_preview_explains_manual_forbid() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot(
                "slot-1",
                0,
                eligible_people=[PERSON_A],
            )
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

    detail = result.unfilled_details[0]

    assert detail.reason_code == "MANUAL_FORBID"
    assert detail.blocking_summary == {
        "MANUAL_FORBID": 1,
    }


def test_preview_explains_previous_rest() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot(
                "slot-1",
                0,
                eligible_people=[PERSON_A],
            )
        ],
        previous_executions=[
            PreviousExecutionSnapshot(
                execution_id=uuid4(),
                person_id=PERSON_A,
                starts_at=datetime(
                    2027,
                    9,
                    29,
                    8,
                    tzinfo=UTC,
                ),
                ends_at=datetime(
                    2027,
                    10,
                    1,
                    0,
                    tzinfo=UTC,
                ),
                rest_minutes=1440,
            )
        ],
    )

    result = solve_assignment(snapshot)

    detail = result.unfilled_details[0]

    assert detail.reason_code == "REST_CONSTRAINT"
    assert detail.blocking_summary == {
        "PREVIOUS_REST": 1,
    }


def test_preview_explains_capacity_shortage() -> None:
    first = make_slot(
        "slot-1",
        0,
        eligible_people=[PERSON_A],
    )

    second = PositionSlotSnapshot(
        id="slot-2",
        occurrence_id=uuid4(),
        duty_type_id=uuid4(),
        position_id=uuid4(),
        starts_at=first.starts_at + timedelta(hours=12),
        ends_at=first.ends_at + timedelta(hours=12),
        rest_minutes=0,
        load_points=100,
        eligible_people=[PERSON_A],
    )

    snapshot = make_snapshot(
        slots=[
            first,
            second,
        ]
    )

    result = solve_assignment(snapshot)

    assert result.filled_count == 1
    assert result.unfilled_count == 1

    detail = result.unfilled_details[0]

    assert detail.reason_code == "CAPACITY_SHORTAGE"
    assert detail.blocking_summary == {
        "ASSIGNED_CONFLICT": 1,
    }


def test_preview_contains_assignment_metrics() -> None:
    snapshot = make_snapshot(
        slots=[
            make_slot(
                "weekend",
                0,
                eligible_people=[PERSON_A],
                load_points=150,
                is_weekend=True,
            ),
            make_slot(
                "holiday",
                2,
                eligible_people=[PERSON_B],
                load_points=200,
                is_holiday=True,
            ),
            make_slot(
                "normal",
                4,
                eligible_people=[PERSON_A],
                load_points=100,
            ),
        ]
    )

    result = solve_assignment(snapshot)

    assert result.status == "OPTIMAL"
    assert result.metrics is not None

    metrics = result.metrics

    assert metrics.total_slots == 3
    assert metrics.filled_count == 3
    assert metrics.unfilled_count == 0
    assert metrics.coverage_percent == 100.0

    assert metrics.assigned_load_points == 450
    assert metrics.weekend_load_points == 150
    assert metrics.holiday_load_points == 200

    people = {item.person_id: item for item in metrics.people}

    assert people[PERSON_A].assignment_count == 2
    assert people[PERSON_A].load_points == 250
    assert people[PERSON_A].weekend_load_points == 150

    assert people[PERSON_B].assignment_count == 1
    assert people[PERSON_B].load_points == 200
    assert people[PERSON_B].holiday_load_points == 200
