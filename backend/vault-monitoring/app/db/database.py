"""PostgreSQL / SQLAlchemy 2.x database configuration.

The engine is created lazily on first use (never at import time). ``init_db()``
is called during application startup and safely creates any missing tables for
the explicitly imported ORM models; it does not drop or alter existing tables.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class DatabaseConnectionError(RuntimeError):
    """Raised when the database engine cannot be created or reached."""


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


# Unbound factory; get_engine() binds it on first use so importing this
# module never requires a valid DATABASE_URL or a live database.
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create (once) and return the shared SQLAlchemy engine.

    Pool settings are sized for a local POC. ``pool_pre_ping`` detects stale
    connections and ``pool_recycle`` avoids server-side idle timeouts.

    Raises:
        DatabaseConnectionError: If DATABASE_URL is malformed or the driver
            is not installed.
    """
    try:
        engine = create_engine(
            settings.DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
        )
    except (ArgumentError, ImportError) as exc:
        logger.error("Could not create database engine: %s", exc)
        raise DatabaseConnectionError(
            "Invalid DATABASE_URL or missing PostgreSQL driver. "
            "Check your .env configuration."
        ) from exc

    SessionLocal.configure(bind=engine)
    return engine


def check_database_connection() -> bool:
    """Return True if a trivial query succeeds; log and return False otherwise."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except (SQLAlchemyError, DatabaseConnectionError) as exc:
        logger.error("Database connectivity check failed: %s", exc)
        return False


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed.

    Uncommitted work is rolled back if the request fails.
    """
    get_engine()
    session = SessionLocal()
    try:
        yield session
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Database error during request; session rolled back")
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Transactional session for non-FastAPI code (scripts, tests, tools).

    Commits on success, rolls back on any exception, always closes.
    """
    get_engine()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create the configured PostgreSQL database and any missing schema objects."""
    logger.info("Starting database initialization")
    target_url = make_url(settings.DATABASE_URL)
    if target_url.get_backend_name() != "postgresql":
        raise DatabaseConnectionError("DATABASE_URL must use PostgreSQL for automatic database creation")
    database = target_url.database
    if not database:
        raise DatabaseConnectionError("DATABASE_URL must include a target database name")
    logger.info("Target PostgreSQL database: %s", database)

    # CREATE DATABASE must run outside a transaction and while connected to a
    # different database. SQLAlchemy's URL object preserves credentials safely.
    admin_engine: Engine | None = None
    try:
        admin_engine = create_engine(
            target_url.set(database="postgres"), isolation_level="AUTOCOMMIT", pool_pre_ping=True
        )
        with admin_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            logger.info("PostgreSQL server connection successful")
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": database},
            ).scalar_one_or_none()
            if exists:
                logger.info("Database '%s' already exists", database)
            else:
                logger.info("Database '%s' does not exist", database)
                logger.info("Creating database '%s'", database)
                quoted_name = admin_engine.dialect.identifier_preparer.quote(database)
                connection.exec_driver_sql(f"CREATE DATABASE {quoted_name}")
                logger.info("Database created successfully")
    except SQLAlchemyError as exc:
        logger.exception("Unable to connect to PostgreSQL server or create database")
        raise DatabaseConnectionError(
            f"Unable to initialize PostgreSQL database '{database}'. Check server access, credentials, and CREATEDB permission."
        ) from exc
    finally:
        if admin_engine is not None:
            admin_engine.dispose()

    logger.info("Connecting to target database")
    engine = get_engine()
    try:
        # Register ORM mappings lazily, without connecting during module import.
        from app.db import models  # noqa: F401
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError as exc:
        logger.exception("Database initialization failed")
        raise DatabaseConnectionError("Database initialization failed") from exc
    logger.info("Database tables verified/created")
    logger.info("Database initialization completed successfully")


__all__ = [
    "Base",
    "DatabaseConnectionError",
    "SessionLocal",
    "check_database_connection",
    "get_db",
    "get_engine",
    "init_db",
    "session_scope",
]
