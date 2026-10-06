"""Data access for employee records."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Employee

logger = get_logger(__name__)


class EmployeeRepositoryError(RuntimeError):
    """Storage failure during employee persistence."""


class DuplicateEmployeeError(EmployeeRepositoryError):
    """Employee business identifier is already in use."""


def _is_unique_violation(exc: IntegrityError, table: str, column: str) -> bool:
    message = str(exc.orig).lower()
    constraint = str(getattr(getattr(exc.orig, "diag", None), "constraint_name", "")).lower()
    expected_names = {
        f"{table}_{column}_key",
        f"ix_{table}_{column}",
    }
    return (
        f"{table}.{column}" in message
        or any(name in message for name in expected_names)
        or constraint in expected_names
    )


class EmployeeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_employee_id(self, employee_id: str) -> Employee | None:
        try:
            return self._session.scalars(
                select(Employee).where(Employee.employee_id == employee_id)
            ).first()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to look up employee '%s'", employee_id)
            raise EmployeeRepositoryError("Failed to load employee") from exc

    def create(
        self, *, employee_id: str, name: str, department: str | None,
        designation: str | None,
    ) -> Employee:
        employee = Employee(
            employee_id=employee_id,
            name=name,
            department=department,
            designation=designation,
        )
        try:
            self._session.add(employee)
            self._session.commit()
            self._session.refresh(employee)
            return employee
        except IntegrityError as exc:
            self._session.rollback()
            if _is_unique_violation(exc, "employees", "employee_id"):
                raise DuplicateEmployeeError(
                    f"employee_id '{employee_id}' is already registered"
                ) from exc
            logger.exception("Employee insert violated a database constraint")
            raise EmployeeRepositoryError("Failed to create employee") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to create employee '%s'", employee_id)
            raise EmployeeRepositoryError("Failed to create employee") from exc
