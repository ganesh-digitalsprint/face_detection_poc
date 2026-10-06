"""Create vault authorization records for existing employees."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.db.authorization_repository import (
    AuthorizedEmployeeRepository,
    DuplicateAuthorizationError,
)
from app.db.employee_repositories import EmployeeRepository
from app.schemas.authorization import AuthorizationCreate, AuthorizationResponse

logger = get_logger(__name__)


class EmployeeNotFoundError(LookupError):
    """No employee exists for the requested business identifier."""


class AuthorizationRegistrationService:
    def __init__(
        self,
        employee_repository: EmployeeRepository,
        authorization_repository: AuthorizedEmployeeRepository,
    ) -> None:
        self._employees = employee_repository
        self._authorizations = authorization_repository

    def register(
        self, employee_id: str, request: AuthorizationCreate
    ) -> AuthorizationResponse:
        employee = self._employees.get_by_employee_id(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee '{employee_id}' was not found")

        if self._authorizations.get_for_employee(employee.id) is not None:
            raise DuplicateAuthorizationError(
                "An authorization record already exists for this employee"
            )

        is_active = request.is_active
        authorized_at = datetime.now(timezone.utc) if is_active else None
        record = self._authorizations.create(
            employee=employee,
            is_active=is_active,
            authorized_at=authorized_at,
            authorization_reason=request.authorization_reason,
            authorized_by=request.authorized_by,
            remarks=request.remarks,
        )
        logger.info(
            "Created %s authorization for employee '%s'",
            "active" if is_active else "inactive",
            employee.employee_id,
        )
        return AuthorizationResponse(
            id=record.id,
            employee_id=employee.employee_id,
            is_active=record.is_active,
            authorized_at=record.authorized_at,
            deauthorized_at=record.deauthorized_at,
            face_registered=record.face_registered,
            authorization_reason=record.authorization_reason,
            authorized_by=record.authorized_by,
            deauthorized_by=record.deauthorized_by,
            remarks=record.remarks,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
