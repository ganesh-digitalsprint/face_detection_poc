from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.db.models import Base


def make_engine(url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, **kwargs)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_database_exists(url: str) -> None:
    """Create only a missing PostgreSQL database; never alter or replace one."""
    target = make_url(url)
    if target.get_backend_name() != "postgresql":
        return
    database = target.database
    if not database:
        raise RuntimeError("ALERT_DATABASE_URL must include a PostgreSQL database name")
    admin_engine = None
    try:
        admin_engine = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT",
                                     pool_pre_ping=True, future=True)
        with admin_engine.connect() as connection:
            exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:database"),
                                        {"database": database}).scalar_one_or_none()
            if not exists:
                quoted = admin_engine.dialect.identifier_preparer.quote(database)
                connection.exec_driver_sql(f"CREATE DATABASE {quoted}")
    except SQLAlchemyError as exc:
        raise RuntimeError(
            f"Unable to initialize PostgreSQL database '{database}'; check server access and CREATEDB permission"
        ) from exc
    finally:
        if admin_engine is not None:
            admin_engine.dispose()


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
