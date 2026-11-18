from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
import pytest

from migrations.notification_email_outbox_v1 import upgrade


def test_outbox_migration_is_repeat_safe_and_preserves_existing_rows(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'outbox.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""CREATE TABLE notification_outbox (
            id TEXT PRIMARY KEY, alert_id TEXT NOT NULL, event_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt_at DATETIME NOT NULL,
            last_error TEXT, provider_message_id TEXT, created_at DATETIME NOT NULL)"""))
        connection.execute(text("""INSERT INTO notification_outbox VALUES
            ('existing', 'alert-old', 'alert.created:alert-old', 'DELIVERED', 1, CURRENT_TIMESTAMP, NULL, 'old-provider', CURRENT_TIMESTAMP)"""))
        upgrade(connection)
        upgrade(connection)
        columns = {column["name"] for column in inspect(connection).get_columns("notification_outbox")}
        assert {"channel", "branch_id", "recipient", "last_attempt_at"} <= columns
        existing = connection.execute(text("SELECT channel, alert_id, status FROM notification_outbox WHERE id='existing'")).one()
        assert existing == ("webhook", "alert-old", "DELIVERED")
        connection.execute(text("""INSERT INTO notification_outbox
            (id,alert_id,event_key,status,attempts,next_attempt_at,created_at,channel,branch_id,recipient)
            VALUES ('email-1','alert-new','email:one','PENDING',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'email','branch-a','one@example.invalid')"""))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("""INSERT INTO notification_outbox
                (id,alert_id,event_key,status,attempts,next_attempt_at,created_at,channel,branch_id,recipient)
                VALUES ('email-2','alert-new','email:two','PENDING',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'email','branch-a','one@example.invalid')"""))
    engine.dispose()
