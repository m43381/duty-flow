from datetime import timedelta
from itertools import combinations
from uuid import UUID

from ortools.sat.python import cp_model

from dutyflow_optimizer.contracts import (
    AssignmentDecision,
    AssignmentOptimizationResult,
    AssignmentOptimizationSnapshot,
    PositionSlotSnapshot,
)


def solve_assignment(
    snapshot: AssignmentOptimizationSnapshot,
) -> AssignmentOptimizationResult:
    model = cp_model.CpModel()

    assignment_vars: dict[
        tuple[str, UUID],
        cp_model.IntVar,
    ] = {}

    unfilled_vars: dict[
        str,
        cp_model.IntVar,
    ] = {}

    # x[slot, person] = 1 означает, что person назначен в slot.
    for slot in snapshot.slots:
        slot_assignment_vars: list[cp_model.IntVar] = []

        for person_id in slot.eligible_people:
            variable = model.new_bool_var(f"x_{slot.id}_{person_id}")

            assignment_vars[(slot.id, person_id)] = variable
            slot_assignment_vars.append(variable)

        # u[slot] = 1 означает, что slot остался незаполненным.
        unfilled = model.new_bool_var(f"unfilled_{slot.id}")
        unfilled_vars[slot.id] = unfilled

        # Для каждого slot должно выполняться ровно одно:
        # либо назначен один человек, либо slot явно UNFILLED.
        model.add(sum(slot_assignment_vars) + unfilled == 1)

    # Один человек не может одновременно стоять
    # в двух конфликтующих слотах.
    #
    # Конфликт существует, если:
    # - интервалы нарядов пересекаются;
    # - либо после первого наряда не успевает пройти
    #   обязательный rest_minutes.
    for first_slot, second_slot in combinations(
        snapshot.slots,
        2,
    ):
        if not _slots_conflict(
            first_slot,
            second_slot,
        ):
            continue

        common_people = set(first_slot.eligible_people) & set(second_slot.eligible_people)

        for person_id in common_people:
            first_variable = assignment_vars[
                (
                    first_slot.id,
                    person_id,
                )
            ]

            second_variable = assignment_vars[
                (
                    second_slot.id,
                    person_id,
                )
            ]

            model.add(first_variable + second_variable <= 1)

    # Locked назначения обязаны сохраниться.
    for assignment in snapshot.existing_assignments:
        if not assignment.locked:
            continue

        variable = assignment_vars[
            (
                assignment.slot_id,
                assignment.person_id,
            )
        ]

        model.add(variable == 1)

    # Ручные ограничения оператора.
    for constraint in snapshot.manual_constraints:
        variable = assignment_vars.get(
            (
                constraint.slot_id,
                constraint.person_id,
            )
        )

        if constraint.type == "FORCE":
            # Контракт уже гарантирует, что FORCE
            # ссылается на eligible person.
            if variable is None:
                raise ValueError("FORCE constraint has no assignment variable")

            model.add(variable == 1)

        elif constraint.type == "FORBID":
            # FORBID может относиться к человеку,
            # который и так не eligible.
            if variable is not None:
                model.add(variable == 0)

    # Первый objective:
    # минимизировать количество незаполненных мест.
    model.minimize(sum(unfilled_vars.values()))

    solver = cp_model.CpSolver()

    solver.parameters.max_time_in_seconds = float(snapshot.settings.time_limit_seconds)

    status = solver.solve(model)
    status_name = _status_name(status)

    if status not in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    ):
        return AssignmentOptimizationResult(
            status=status_name,
            filled_count=0,
            unfilled_count=0,
        )

    assignments: list[AssignmentDecision] = []
    unfilled_slots: list[str] = []

    for slot in snapshot.slots:
        assigned = False

        for person_id in slot.eligible_people:
            variable = assignment_vars[
                (
                    slot.id,
                    person_id,
                )
            ]

            if solver.value(variable):
                assignments.append(
                    AssignmentDecision(
                        slot_id=slot.id,
                        person_id=person_id,
                    )
                )

                assigned = True
                break

        if not assigned and solver.value(unfilled_vars[slot.id]):
            unfilled_slots.append(slot.id)

    return AssignmentOptimizationResult(
        status=status_name,
        assignments=assignments,
        unfilled_slots=unfilled_slots,
        filled_count=len(assignments),
        unfilled_count=len(unfilled_slots),
    )


def _slots_conflict(
    first_slot: PositionSlotSnapshot,
    second_slot: PositionSlotSnapshot,
) -> bool:
    if second_slot.starts_at < first_slot.starts_at:
        first_slot, second_slot = (
            second_slot,
            first_slot,
        )

    protected_until = first_slot.ends_at + timedelta(
        minutes=first_slot.rest_minutes,
    )

    return protected_until > second_slot.starts_at


def _status_name(status: int) -> str:
    statuses = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }

    return statuses.get(
        status,
        "UNKNOWN",
    )
