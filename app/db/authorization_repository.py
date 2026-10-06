"""Persistence operations for employee vault authorization records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import AuthorizedEmployee, Employee

logger = get_logger(__name__)


class AuthorizationRepositoryError(RuntimeError):
    """A storage operation for an authorization record failed."""


class DuplicateAuthorizationError(AuthorizationRepositoryError):
    """An authorization record already exists for the employee."""


def _is_authorization_unique_violation(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower()
    constraint = str(getattr(getattr(exc.orig, "diag", None), "constraint_name", "")).lower()
    expected = {
        "authorized_employees_employee_id_key",
        "ix_authorized_employees_employee_id",
    }
    return (
        "authorized_employees.employee_id" in message
        or any(name in message for name in expected)
        or constraint in expected
    )


class AuthorizedEmployeeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_employee(self, employee_pk: int) -> AuthorizedEmployee | None:
        try:
            return self._session.scalars(
                select(AuthorizedEmployee).where(
                    AuthorizedEmployee.employee_id == employee_pk
                )
            ).first()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to load authorization for employee id=%s", employee_pk)
            raise AuthorizationRepositoryError("Failed to load authorization") from exc

    def set_face_registered(
        self, authorization: AuthorizedEmployee, value: bool
    ) -> AuthorizedEmployee:
        try:
            authorization.face_registered = value
            self._session.add(authorization)
            self._session.commit()
            return authorization
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception(
                "Failed to update face enrollment state for authorization id=%s",
                authorization.id,
            )
            raise AuthorizationRepositoryError(
                "Failed to update face enrollment state"
            ) from exc

    def create(
        self,
        *,
        employee: Employee,
        is_active: bool,
        authorized_at: datetime | None,
        authorization_reason: str | None,
        authorized_by: str | None,
        remarks: str | None,
    ) -> AuthorizedEmployee:
        record = AuthorizedEmployee(
            employee=employee,
            is_active=is_active,
            authorized_at=authorized_at,
            authorization_reason=authorization_reason,
            authorized_by=authorized_by,
            remarks=remarks,
        )
        try:
            self._session.add(record)
            self._session.commit()
            self._session.refresh(record)
            return record
        except IntegrityError as exc:
            self._session.rollback()
            if _is_authorization_unique_violation(exc):
                raise DuplicateAuthorizationError(
                    "An authorization record already exists for this employee"
                ) from exc
            logger.exception("Authorization insert violated a database constraint")
            raise AuthorizationRepositoryError("Failed to create authorization") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to create authorization for employee id=%s", employee.id)
            raise AuthorizationRepositoryError("Failed to create authorization") from exc
