"""Persistence tests for employee and vault authorization ORM mappings."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import AuthorizedEmployee, Employee


def test_employee_and_authorization_tables_are_registered():
    assert "employees" in Base.metadata.tables
    assert "authorized_employees" in Base.metadata.tables


def test_authorization_employee_id_is_indexed_unique_and_references_employee():
    column = AuthorizedEmployee.__table__.c.employee_id
    assert column.nullable is False
    assert column.unique is True
    assert column.index is True
    foreign_key = next(iter(column.foreign_keys))
    assert foreign_key.target_fullname == "employees.id"
    assert foreign_key.ondelete == "RESTRICT"
    assert Employee.authorized_employee.property.uselist is False


def test_defaults_and_timezone_aware_timestamps():
    auth_table = AuthorizedEmployee.__table__
    assert auth_table.c.is_active.default.arg is False
    assert auth_table.c.is_active.server_default.arg.text == "false"
    assert auth_table.c.face_registered.default.arg is False
    assert auth_table.c.face_registered.server_default.arg.text == "false"
    for table in (Employee.__table__, auth_table):
        assert table.c.created_at.type.timezone is True
        assert table.c.updated_at.type.timezone is True
        assert table.c.created_at.server_default is not None
        assert table.c.updated_at.onupdate is not None
    assert auth_table.c.authorized_at.onupdate is None
    assert auth_table.c.deauthorized_at.onupdate is None


def test_create_all_is_repeatable_preserves_rows_and_supports_partial_schema():
    engine = create_engine("sqlite:///:memory:")
    try:
        # Model package imports register all three existing/new mapped tables.
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            employee = Employee(employee_id="EMP001", name="A. Employee")
            session.add(employee)
            session.flush()
            authorization = AuthorizedEmployee(employee=employee)
            session.add(authorization)
            session.commit()
            employee_pk = employee.id
            authorization_pk = authorization.id
            assert authorization.is_active is False
            assert authorization.face_registered is False
            assert employee.authorized_employee is authorization

        # Subsequent initialization leaves existing tables and data intact.
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            assert session.get(Employee, employee_pk) is not None
            assert session.get(AuthorizedEmployee, authorization_pk) is not None

        # A missing authorization table is created without dropping employees.
        AuthorizedEmployee.__table__.drop(engine)
        Base.metadata.create_all(engine)
        assert inspect(engine).has_table("authorized_employees")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM employees")).scalar_one() == 1
    finally:
        engine.dispose()


def test_face_registration_and_authorization_are_independent_states():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            employee = Employee(employee_id="EMP002", name="B. Employee")
            session.add(employee)
            session.flush()
            active_without_face = AuthorizedEmployee(
                employee=employee,
                is_active=True,
                face_registered=False,
            )
            session.add(active_without_face)
            session.commit()
            assert active_without_face.is_active is True
            assert active_without_face.face_registered is False
    finally:
        engine.dispose()
