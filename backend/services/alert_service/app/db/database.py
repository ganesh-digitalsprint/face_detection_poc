from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.models import Base


def make_engine(url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, **kwargs)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def initialize(engine) -> None:
    Base.metadata.create_all(engine)
    # Audit immutability is enforced in the database for the supported engines.
    with engine.begin() as connection:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            connection.execute(text("CREATE TRIGGER IF NOT EXISTS alert_audit_no_update BEFORE UPDATE ON alert_audit BEGIN SELECT RAISE(ABORT, 'alert_audit is append-only'); END"))
            connection.execute(text("CREATE TRIGGER IF NOT EXISTS alert_audit_no_delete BEFORE DELETE ON alert_audit BEGIN SELECT RAISE(ABORT, 'alert_audit is append-only'); END"))
        elif dialect == "postgresql":
            connection.execute(text("""CREATE OR REPLACE FUNCTION alert_audit_reject_mutation() RETURNS trigger AS $$
                BEGIN RAISE EXCEPTION 'alert_audit is append-only'; END; $$ LANGUAGE plpgsql"""))
            connection.execute(text("""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_alert_audit_append_only') THEN
                  EXECUTE 'CREATE TRIGGER trg_alert_audit_append_only BEFORE UPDATE OR DELETE ON alert_audit '
                    || 'FOR EACH ROW EXECUTE FUNCTION alert_audit_reject_mutation()';
                END IF;
                END $$"""))
