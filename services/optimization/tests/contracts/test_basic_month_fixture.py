import json
from pathlib import Path
from uuid import UUID

from dutyflow_optimizer.contracts import AssignmentOptimizationSnapshot

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "basic_month.json"


def test_basic_month_fixture_is_valid() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    snapshot = AssignmentOptimizationSnapshot.model_validate(payload)

    assert len(snapshot.people) == 4
    assert len(snapshot.slots) == 6
    assert len(snapshot.existing_assignments) == 1
    assert len(snapshot.manual_constraints) == 1

    assert snapshot.existing_assignments[0].locked is True

    assert snapshot.existing_assignments[0].person_id == UUID(
        "20000000-0000-0000-0000-000000000001"
    )


def test_basic_month_can_be_serialized_back_to_json() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    snapshot = AssignmentOptimizationSnapshot.model_validate(payload)

    serialized = snapshot.model_dump_json()

    assert '"schema_version":"1.0"' in serialized
    assert '"slot-03"' in serialized
