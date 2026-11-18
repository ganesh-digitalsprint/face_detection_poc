"""Add branch notification settings (revision 0002; additive and repeat-safe).

Apply only after approval against the selected Alert Service database:
    python -m migrations.branch_notification_settings_v1 upgrade <DATABASE_URL>

Rollback is intentionally a separate explicit operation. Export the table first if its
settings must be retained; see the Alert Service README for the rollback procedure.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine

from app.db.models import BranchNotificationSettings


def upgrade(connection) -> None:
    BranchNotificationSettings.__table__.create(connection, checkfirst=True)


def downgrade(connection) -> None:
    BranchNotificationSettings.__table__.drop(connection, checkfirst=True)


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"upgrade", "downgrade"}:
        raise SystemExit("usage: python -m migrations.branch_notification_settings_v1 <upgrade|downgrade> <DATABASE_URL>")
    engine = create_engine(sys.argv[2], future=True)
    try:
        with engine.begin() as connection:
            (upgrade if sys.argv[1] == "upgrade" else downgrade)(connection)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
