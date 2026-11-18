"""Extend the existing notification outbox for per-recipient email delivery.

Additive revision 0003. It is deliberately not applied by service startup.
"""
from __future__ import annotations

import sys
import os

from sqlalchemy import create_engine, inspect, text


def upgrade(connection) -> None:
    dialect = connection.dialect.name
    columns = {column["name"] for column in inspect(connection).get_columns("notification_outbox")}
    additions = {
        "channel": "VARCHAR(16) NOT NULL DEFAULT 'webhook'",
        "branch_id": "VARCHAR(128)",
        "recipient": "VARCHAR(320)",
        "last_attempt_at": "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME",
    }
    for name, definition in additions.items():
        if name in columns:
            continue
        if dialect == "postgresql":
            connection.execute(text(f"ALTER TABLE notification_outbox ADD COLUMN IF NOT EXISTS {name} {definition}"))
        else:
            connection.execute(text(f"ALTER TABLE notification_outbox ADD COLUMN {name} {definition}"))
    # Each alert-recipient pair can be queued once. Webhook rows have no recipient
    # and continue using their existing unique event_key.
    if dialect == "postgresql":
        connection.execute(text("""CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_email_recipient
            ON notification_outbox (alert_id, recipient) WHERE channel = 'email'"""))
    elif dialect == "sqlite":
        connection.execute(text("""CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_email_recipient
            ON notification_outbox (alert_id, recipient) WHERE channel = 'email'"""))
    else:
        raise RuntimeError(f"Unsupported migration dialect: {dialect}")


def downgrade(connection) -> None:
    """Drop email outbox columns after exporting delivery rows if they must be kept."""
    connection.execute(text("DROP INDEX IF EXISTS uq_notification_email_recipient"))
    if connection.dialect.name == "postgresql":
        connection.execute(text("""ALTER TABLE notification_outbox
            DROP COLUMN IF EXISTS last_attempt_at, DROP COLUMN IF EXISTS recipient,
            DROP COLUMN IF EXISTS branch_id, DROP COLUMN IF EXISTS channel"""))
    elif connection.dialect.name == "sqlite":
        # SQLite builds supporting DROP COLUMN are used by the development/test runtime.
        for name in ("last_attempt_at", "recipient", "branch_id", "channel"):
            columns = {column["name"] for column in inspect(connection).get_columns("notification_outbox")}
            if name in columns:
                connection.execute(text(f"ALTER TABLE notification_outbox DROP COLUMN {name}"))


def main() -> None:
    if len(sys.argv) not in {2, 3} or sys.argv[1] not in {"upgrade", "downgrade"}:
        raise SystemExit("usage: python -m migrations.notification_email_outbox_v1 <upgrade|downgrade> [DATABASE_URL]")
    database_url = sys.argv[2] if len(sys.argv) == 3 else os.getenv("ALERT_DATABASE_URL", "")
    if not database_url:
        raise SystemExit("Set ALERT_DATABASE_URL from backend/services/alert_service/.env before running the migration.")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            (upgrade if sys.argv[1] == "upgrade" else downgrade)(connection)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
