"""Employee identity registration workflow."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.employee_repositories import (
    DuplicateEmployeeError,
    EmployeeRepository,
    EmployeeRepositoryError,
)
from app.schemas.employee import EmployeeCreate, EmployeeResponse

logger = get_logger(__name__)


class EmployeeInputError(ValueError):
    """Employee input failed validation."""


class EmployeeRegistrationService:
    def __init__(self, session: Session, repository: EmployeeRepository | None = None) -> None:
        self._employees = repository or EmployeeRepository(session)

    def register(self, payload: EmployeeCreate | dict) -> EmployeeResponse:
        try:
            data = payload if isinstance(payload, EmployeeCreate) else EmployeeCreate.model_validate(payload)
        except ValidationError as exc:
            raise EmployeeInputError(_summarize(exc)) from exc

        if self._employees.get_by_employee_id(data.employee_id) is not None:
            raise DuplicateEmployeeError(
                f"employee_id '{data.employee_id}' is already registered"
            )
        employee = self._employees.create(
            employee_id=data.employee_id,
            name=data.name,
            department=data.department,
            designation=data.designation,
        )
        logger.info("Registered employee '%s' (id=%s)", employee.employee_id, employee.id)
        return EmployeeResponse.model_validate(employee)


def _summarize(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    )


__all__ = [
    "EmployeeInputError",
    "EmployeeRegistrationService",
    "EmployeeRepositoryError",
]
