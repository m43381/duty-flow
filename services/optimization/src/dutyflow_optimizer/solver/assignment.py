from datetime import timedelta
from itertools import combinations
from typing import Literal
from uuid import UUID

from ortools.sat.python import cp_model

from dutyflow_optimizer.contracts import (
    AssignmentDecision,
    AssignmentOptimizationResult,
    AssignmentOptimizationSnapshot,
    PersonSnapshot,
    PositionSlotSnapshot,
)

FairnessDimension = Literal[
    "total",
    "weekend",
    "holiday",
    "count",
]


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

    # Фактически отработанные наряды до начала периода
    # могут блокировать первые слоты нового периода.
    for execution in snapshot.previous_executions:
        protected_until = execution.ends_at + timedelta(
            minutes=execution.rest_minutes,
        )

        for slot in snapshot.slots:
            if execution.person_id not in slot.eligible_people:
                continue

            if protected_until <= slot.starts_at:
                continue

            variable = assignment_vars[
                (
                    slot.id,
                    execution.person_id,
                )
            ]

            model.add(variable == 0)

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
            if variable is None:
                raise ValueError("FORCE constraint has no assignment variable")

            model.add(variable == 1)

        elif constraint.type == "FORBID":
            if variable is not None:
                model.add(variable == 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(snapshot.settings.time_limit_seconds)

    # Этап 1: coverage.
    model.minimize(sum(unfilled_vars.values()))

    status = solver.solve(model)

    if not _has_solution(status):
        return _empty_result(status)

    if status != cp_model.OPTIMAL:
        return _build_result(
            snapshot,
            solver,
            status,
            assignment_vars,
            unfilled_vars,
        )

    best_unfilled = sum(solver.value(variable) for variable in unfilled_vars.values())

    # Ни один следующий fairness-этап не имеет права
    # ухудшить максимально возможное заполнение.
    model.add(sum(unfilled_vars.values()) == best_unfilled)

    # Этапы 2-3: главная fairness по общей нагрузке.
    total_fairness = _add_fairness_dimension(
        model,
        snapshot,
        assignment_vars,
        dimension="total",
    )

    if total_fairness is not None:
        status, completed = _optimize_fairness_dimension(
            model,
            solver,
            total_fairness,
        )

        if not _has_solution(status):
            return _empty_result(status)

        if not completed:
            return _build_result(
                snapshot,
                solver,
                status,
                assignment_vars,
                unfilled_vars,
            )

    # Этапы 4-5: fairness по выходным.
    weekend_fairness = _add_fairness_dimension(
        model,
        snapshot,
        assignment_vars,
        dimension="weekend",
    )

    if weekend_fairness is not None:
        status, completed = _optimize_fairness_dimension(
            model,
            solver,
            weekend_fairness,
        )

        if not _has_solution(status):
            return _empty_result(status)

        if not completed:
            return _build_result(
                snapshot,
                solver,
                status,
                assignment_vars,
                unfilled_vars,
            )

    # Этапы 6-7: fairness по праздникам.
    holiday_fairness = _add_fairness_dimension(
        model,
        snapshot,
        assignment_vars,
        dimension="holiday",
    )

    if holiday_fairness is not None:
        status, completed = _optimize_fairness_dimension(
            model,
            solver,
            holiday_fairness,
        )

        if not _has_solution(status):
            return _empty_result(status)

        if not completed:
            return _build_result(
                snapshot,
                solver,
                status,
                assignment_vars,
                unfilled_vars,
            )

    # Этапы 8-9: fairness по количеству нарядов.
    #
    # Это более низкий приоритет, чем реальная weighted load.
    # Поэтому solver сначала сохраняет оптимальную общую нагрузку,
    # выходные и праздники, и только затем выравнивает количество.
    count_fairness = _add_fairness_dimension(
        model,
        snapshot,
        assignment_vars,
        dimension="count",
    )

    if count_fairness is not None:
        status, completed = _optimize_fairness_dimension(
            model,
            solver,
            count_fairness,
        )

        if not _has_solution(status):
            return _empty_result(status)

        if not completed:
            return _build_result(
                snapshot,
                solver,
                status,
                assignment_vars,
                unfilled_vars,
            )

    return _build_result(
        snapshot,
        solver,
        status,
        assignment_vars,
        unfilled_vars,
    )


def _optimize_fairness_dimension(
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    fairness: tuple[
        cp_model.IntVar,
        list[cp_model.IntVar],
    ],
) -> tuple[int, bool]:
    max_deviation, deviations = fairness

    # Сначала минимизируем худшее индивидуальное отклонение.
    model.minimize(max_deviation)

    status = solver.solve(model)

    if not _has_solution(status):
        return status, False

    if status != cp_model.OPTIMAL:
        return status, False

    best_max_deviation = solver.value(max_deviation)

    model.add(max_deviation == best_max_deviation)

    # Затем, не ухудшая worst-case, минимизируем
    # сумму отклонений всех людей.
    total_deviation = sum(deviations)

    model.minimize(total_deviation)

    status = solver.solve(model)

    if not _has_solution(status):
        return status, False

    if status != cp_model.OPTIMAL:
        return status, False

    best_total_deviation = sum(solver.value(deviation) for deviation in deviations)

    # Следующая fairness-размерность не имеет права
    # ухудшить уже найденный optimum этой размерности.
    model.add(total_deviation == best_total_deviation)

    return status, True


def _add_fairness_dimension(
    model: cp_model.CpModel,
    snapshot: AssignmentOptimizationSnapshot,
    assignment_vars: dict[
        tuple[str, UUID],
        cp_model.IntVar,
    ],
    *,
    dimension: FairnessDimension,
) -> (
    tuple[
        cp_model.IntVar,
        list[cp_model.IntVar],
    ]
    | None
):
    slot_by_id = {slot.id: slot for slot in snapshot.slots}

    person_variables: dict[
        UUID,
        list[tuple[cp_model.IntVar, int]],
    ] = {}

    total_dimension_load = sum(
        _slot_dimension_load(
            slot,
            dimension,
        )
        for slot in snapshot.slots
    )

    if total_dimension_load == 0:
        return None

    total_assigned_terms = []

    for (
        slot_id,
        person_id,
    ), variable in assignment_vars.items():
        slot = slot_by_id[slot_id]

        load_points = _slot_dimension_load(
            slot,
            dimension,
        )

        if load_points == 0:
            continue

        total_assigned_terms.append(load_points * variable)

        person_variables.setdefault(
            person_id,
            [],
        ).append(
            (
                variable,
                load_points,
            )
        )

    if not person_variables:
        return None

    participating_people = [person for person in snapshot.people if person.id in person_variables]

    total_fairness_weight = sum(person.fairness_weight for person in participating_people)

    if total_fairness_weight == 0:
        return None

    total_assigned_load = model.new_int_var(
        0,
        total_dimension_load,
        f"{dimension}_assigned_load",
    )

    model.add(total_assigned_load == sum(total_assigned_terms))

    history_corrections = {
        person.id: _history_correction_points(
            actual_load_points=_history_actual(
                person,
                dimension,
            ),
            expected_load_points=_history_expected(
                person,
                dimension,
            ),
            fairness_weight=person.fairness_weight,
            total_fairness_weight=total_fairness_weight,
            total_load_points=total_dimension_load,
            max_correction_percent=(snapshot.settings.max_history_correction_percent),
        )
        for person in participating_people
    }

    # Историческая поправка может сместить цель максимум
    # на 100% базовой доли, поэтому удвоенного диапазона
    # достаточно для absolute deviation.
    max_scaled_deviation = 2 * total_dimension_load * total_fairness_weight

    deviations: list[cp_model.IntVar] = []

    for person in participating_people:
        planned_load = model.new_int_var(
            0,
            total_dimension_load,
            f"{dimension}_planned_load_{person.id}",
        )

        person_load_terms = [
            load_points * variable for variable, load_points in person_variables[person.id]
        ]

        model.add(planned_load == sum(person_load_terms))

        deviation = model.new_int_var(
            0,
            max_scaled_deviation,
            f"{dimension}_deviation_{person.id}",
        )

        correction_points = history_corrections[person.id]

        target_scaled = (
            total_assigned_load * person.fairness_weight + correction_points * total_fairness_weight
        )

        planned_scaled = planned_load * total_fairness_weight

        model.add_abs_equality(
            deviation,
            planned_scaled - target_scaled,
        )

        deviations.append(deviation)

    max_deviation = model.new_int_var(
        0,
        max_scaled_deviation,
        f"{dimension}_max_deviation",
    )

    for deviation in deviations:
        model.add(max_deviation >= deviation)

    return max_deviation, deviations


def _slot_dimension_load(
    slot: PositionSlotSnapshot,
    dimension: FairnessDimension,
) -> int:
    if dimension == "total":
        return slot.load_points

    if dimension == "weekend":
        if slot.calendar.is_weekend:
            return slot.load_points

        return 0

    if dimension == "holiday":
        if slot.calendar.is_holiday:
            return slot.load_points

        return 0

    if dimension == "count":
        return 1

    raise ValueError(f"unsupported fairness dimension: {dimension}")


def _history_actual(
    person: PersonSnapshot,
    dimension: FairnessDimension,
) -> int:
    if dimension == "total":
        return person.history.actual_load_points

    if dimension == "weekend":
        return person.history.weekend_load_points

    if dimension == "holiday":
        return person.history.holiday_load_points

    if dimension == "count":
        return person.history.duty_count

    raise ValueError(f"unsupported fairness dimension: {dimension}")


def _history_expected(
    person: PersonSnapshot,
    dimension: FairnessDimension,
) -> int:
    if dimension == "total":
        return person.history.expected_load_points

    if dimension == "weekend":
        return person.history.expected_weekend_load_points

    if dimension == "holiday":
        return person.history.expected_holiday_load_points

    if dimension == "count":
        return person.history.expected_duty_count

    raise ValueError(f"unsupported fairness dimension: {dimension}")


def _history_correction_points(
    *,
    actual_load_points: int,
    expected_load_points: int,
    fairness_weight: int,
    total_fairness_weight: int,
    total_load_points: int,
    max_correction_percent: int,
) -> int:
    if fairness_weight == 0 or total_fairness_weight == 0 or max_correction_percent == 0:
        return 0

    history_debt = expected_load_points - actual_load_points

    correction_limit = (
        total_load_points
        * fairness_weight
        * max_correction_percent
        // (total_fairness_weight * 100)
    )

    return max(
        -correction_limit,
        min(
            history_debt,
            correction_limit,
        ),
    )


def _build_result(
    snapshot: AssignmentOptimizationSnapshot,
    solver: cp_model.CpSolver,
    status: int,
    assignment_vars: dict[
        tuple[str, UUID],
        cp_model.IntVar,
    ],
    unfilled_vars: dict[
        str,
        cp_model.IntVar,
    ],
) -> AssignmentOptimizationResult:
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
        status=_status_name(status),
        assignments=assignments,
        unfilled_slots=unfilled_slots,
        filled_count=len(assignments),
        unfilled_count=len(unfilled_slots),
    )


def _empty_result(
    status: int,
) -> AssignmentOptimizationResult:
    return AssignmentOptimizationResult(
        status=_status_name(status),
        filled_count=0,
        unfilled_count=0,
    )


def _has_solution(status: int) -> bool:
    return status in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
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
