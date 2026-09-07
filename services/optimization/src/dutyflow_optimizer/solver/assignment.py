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

    # Этап 1.
    # Сначала минимизируем число незаполненных слотов.
    model.minimize(sum(unfilled_vars.values()))

    status = solver.solve(model)

    if status not in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    ):
        return _empty_result(status)

    # Если solver не доказал оптимальность coverage за отведённое время,
    # не переходим к fairness и возвращаем лучшее найденное решение.
    if status != cp_model.OPTIMAL:
        return _build_result(
            snapshot,
            solver,
            status,
            assignment_vars,
            unfilled_vars,
        )

    best_unfilled = sum(solver.value(variable) for variable in unfilled_vars.values())

    # Fairness никогда не имеет права ухудшить coverage.
    model.add(sum(unfilled_vars.values()) == best_unfilled)

    fairness = _add_load_fairness(
        model,
        snapshot,
        assignment_vars,
    )

    # Если fairness посчитать не для кого, coverage-решение уже финальное.
    if fairness is None:
        return _build_result(
            snapshot,
            solver,
            status,
            assignment_vars,
            unfilled_vars,
        )

    max_deviation, deviations = fairness

    # Этап 2.
    # Минимизируем худшее отклонение от целевой нагрузки.
    model.minimize(max_deviation)

    status = solver.solve(model)

    if status not in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    ):
        return _empty_result(status)

    if status != cp_model.OPTIMAL:
        return _build_result(
            snapshot,
            solver,
            status,
            assignment_vars,
            unfilled_vars,
        )

    best_max_deviation = solver.value(max_deviation)

    # Следующий этап не может ухудшить уже достигнутый worst-case.
    model.add(max_deviation == best_max_deviation)

    # Этап 3.
    # Среди решений с тем же worst-case минимизируем
    # суммарное отклонение всех людей.
    model.minimize(sum(deviations))

    status = solver.solve(model)

    if status not in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    ):
        return _empty_result(status)

    return _build_result(
        snapshot,
        solver,
        status,
        assignment_vars,
        unfilled_vars,
    )


def _add_load_fairness(
    model: cp_model.CpModel,
    snapshot: AssignmentOptimizationSnapshot,
    assignment_vars: dict[
        tuple[str, UUID],
        cp_model.IntVar,
    ],
) -> tuple[cp_model.IntVar, list[cp_model.IntVar]] | None:
    slot_by_id = {slot.id: slot for slot in snapshot.slots}

    person_variables: dict[
        UUID,
        list[tuple[cp_model.IntVar, int]],
    ] = {}

    total_load_points = sum(slot.load_points for slot in snapshot.slots)

    if total_load_points == 0:
        return None

    total_assigned_terms = []

    for (slot_id, person_id), variable in assignment_vars.items():
        load_points = slot_by_id[slot_id].load_points

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
        total_load_points,
        "total_assigned_load",
    )

    model.add(total_assigned_load == sum(total_assigned_terms))

    # Историческая поправка ограничена долей от потенциальной
    # целевой нагрузки текущего периода. При полном coverage это
    # ровно max_history_correction_percent от текущей цели.
    #
    # Даже при экстремальной истории прошлые месяцы не смогут
    # полностью "перетянуть" новый график на себя.
    history_corrections = {
        person.id: _history_correction_points(
            actual_load_points=person.history.actual_load_points,
            expected_load_points=person.history.expected_load_points,
            fairness_weight=person.fairness_weight,
            total_fairness_weight=total_fairness_weight,
            total_load_points=total_load_points,
            max_correction_percent=(snapshot.settings.max_history_correction_percent),
        )
        for person in participating_people
    }

    # Коррекция может смещать цель вверх или вниз максимум на 100%
    # базовой доли, поэтому удвоенного диапазона достаточно.
    max_scaled_deviation = 2 * total_load_points * total_fairness_weight

    deviations: list[cp_model.IntVar] = []

    for person in participating_people:
        planned_load = model.new_int_var(
            0,
            total_load_points,
            f"planned_load_{person.id}",
        )

        person_load_terms = [
            load_points * variable for variable, load_points in person_variables[person.id]
        ]

        model.add(planned_load == sum(person_load_terms))

        deviation = model.new_int_var(
            0,
            max_scaled_deviation,
            f"load_deviation_{person.id}",
        )

        correction_points = history_corrections[person.id]

        # Базовая цель:
        #
        # total_assigned_load
        #     * fairness_weight
        #     / total_fairness_weight
        #
        # Затем добавляем ограниченную историческую поправку:
        #
        # expected_history - actual_history
        #
        # Если человек был перегружен, correction отрицательная.
        # Если был недогружен — положительная.
        #
        # Деления в CP-SAT избегаем и работаем
        # в масштабированных целых значениях.
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
        "max_load_deviation",
    )

    for deviation in deviations:
        model.add(max_deviation >= deviation)

    return max_deviation, deviations


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

    # Базовая потенциальная цель человека на текущий период.
    # Берём floor, чтобы поправка гарантированно не превысила
    # установленный процент.
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
