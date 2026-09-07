from datetime import UTC, datetime
from uuid import uuid4

import pytest
from dutyflow_optimizer.contracts import (
    AssignmentOptimizationSnapshot,
    ExistingAssignmentSnapshot,
    ManualConstraint,
    PeriodSnapshot,
    PersonSnapshot,
    PositionSlotSnapshot,
)
from pydantic import ValidationError


def test_force_rejects_ineligible_person() -> None:
    eligible_person_id = uuid4()
    ineligible_person_id = uuid4()

    with pytest.raises(
        ValidationError,
        match="FORCE constraint references person",
    ):
        AssignmentOptimizationSnapshot(
            run_id=uuid4(),
            unit_id=uuid4(),
            period=PeriodSnapshot(
                starts_at=datetime(2027, 10, 1, tzinfo=UTC),
                ends_at=datetime(2027, 11, 1, tzinfo=UTC),
            ),
            people=[
                PersonSnapshot(id=eligible_person_id),
                PersonSnapshot(id=ineligible_person_id),
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
                    eligible_people=[
                        eligible_person_id,
                    ],
                )
            ],
            manual_constraints=[
                ManualConstraint(
                    type="FORCE",
                    slot_id="slot-1",
                    person_id=ineligible_person_id,
                )
            ],
        )


def test_locked_assignment_must_reference_eligible_person() -> None:
    eligible_person_id = uuid4()
    ineligible_person_id = uuid4()

    with pytest.raises(
        ValidationError,
        match="not eligible",
    ):
        AssignmentOptimizationSnapshot(
            run_id=uuid4(),
            unit_id=uuid4(),
            period=PeriodSnapshot(
                starts_at=datetime(2027, 10, 1, tzinfo=UTC),
                ends_at=datetime(2027, 11, 1, tzinfo=UTC),
            ),
            people=[
                PersonSnapshot(id=eligible_person_id),
                PersonSnapshot(id=ineligible_person_id),
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
                    eligible_people=[
                        eligible_person_id,
                    ],
                )
            ],
            existing_assignments=[
                ExistingAssignmentSnapshot(
                    assignment_id=uuid4(),
                    slot_id="slot-1",
                    person_id=ineligible_person_id,
                    source="MANUAL",
                    locked=True,
                )
            ],
        )


def test_valid_assignment_snapshot() -> None:
    person_id = uuid4()

    snapshot = AssignmentOptimizationSnapshot(
        run_id=uuid4(),
        unit_id=uuid4(),
        period=PeriodSnapshot(
            starts_at=datetime(2027, 10, 1, tzinfo=UTC),
            ends_at=datetime(2027, 11, 1, tzinfo=UTC),
        ),
        people=[
            PersonSnapshot(
                id=person_id,
            )
        ],
        slots=[
            PositionSlotSnapshot(
                id="slot-1",
                occurrence_id=uuid4(),
                duty_type_id=uuid4(),
                position_id=uuid4(),
                starts_at=datetime(2027, 10, 10, 18, tzinfo=UTC),
                ends_at=datetime(2027, 10, 11, 18, tzinfo=UTC),
                rest_minutes=1440,
                load_points=200,
                eligible_people=[person_id],
            )
        ],
    )

    assert snapshot.schema_version == "1.0"
    assert snapshot.people[0].id == person_id
    assert snapshot.slots[0].load_points == 200


def test_period_rejects_invalid_time_range() -> None:
    with pytest.raises(
        ValidationError,
        match="period ends_at must be later than starts_at",
    ):
        PeriodSnapshot(
            starts_at=datetime(2027, 10, 2, tzinfo=UTC),
            ends_at=datetime(2027, 10, 1, tzinfo=UTC),
        )


def test_slot_rejects_negative_load() -> None:
    with pytest.raises(ValidationError):
        PositionSlotSnapshot(
            id="slot-1",
            occurrence_id=uuid4(),
            duty_type_id=uuid4(),
            position_id=uuid4(),
            starts_at=datetime(2027, 10, 10, 18, tzinfo=UTC),
            ends_at=datetime(2027, 10, 11, 18, tzinfo=UTC),
            load_points=-100,
        )


def test_snapshot_rejects_unknown_eligible_person() -> None:
    known_person_id = uuid4()
    unknown_person_id = uuid4()

    with pytest.raises(
        ValidationError,
        match="references unknown eligible people",
    ):
        AssignmentOptimizationSnapshot(
            run_id=uuid4(),
            unit_id=uuid4(),
            period=PeriodSnapshot(
                starts_at=datetime(2027, 10, 1, tzinfo=UTC),
                ends_at=datetime(2027, 11, 1, tzinfo=UTC),
            ),
            people=[
                PersonSnapshot(
                    id=known_person_id,
                )
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
                    eligible_people=[
                        unknown_person_id,
                    ],
                )
            ],
        )
