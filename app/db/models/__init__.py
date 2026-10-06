"""SQLAlchemy ORM models and compatibility exports."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PersonStatus(str, enum.Enum):
    """Lifecycle status of a legacy face-recognition person record."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class Person(Base):
    """Legacy person table retained for existing recognition repositories."""

    __tablename__ = "persons"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_persons_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_code: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PersonStatus.ACTIVE.value, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"Person(id={self.id!r}, person_code={self.person_code!r})"


# Import explicitly so these tables are registered before init_db calls
# Base.metadata.create_all(). Person remains exported for current repositories.
from app.db.models.employee import Employee  # noqa: E402
from app.db.models.authorized_employee import (  # noqa: E402
    AuthorizedEmployee,
)

__all__ = [
    "AuthorizedEmployee",
    "Employee",
    "Person",
    "PersonStatus",
]
