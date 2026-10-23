from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.api.errors import install_error_handlers
from app.api.routes.employees import employee_router
from app.db.database import Base
from app.db.models import AuthorizedEmployee, Employee


def make_client():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(employee_router)
    engine = create_engine(
        'sqlite:///:memory:',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), session, engine


def test_status_lookup_identifies_employee_with_no_authorization():
    client, session, engine = make_client()
    session.add(Employee(employee_id='1111', name='Ganesh'))
    session.commit()

    response = client.get('/api/v1/employees/1111/registration-status')

    assert response.status_code == 200
    status = response.json()
    assert status['employee_id'] == '1111'
    assert status['authorization_exists'] is False
    assert status['authorization_active'] is None
    assert status['face_registered'] is False
    session.close()
    engine.dispose()


def test_status_lookup_identifies_face_enrollment_progress():
    client, session, engine = make_client()
    employee = Employee(employee_id='2222', name='Ada')
    session.add(employee)
    session.flush()
    session.add(AuthorizedEmployee(employee_id=employee.id, is_active=True, face_registered=True))
    session.commit()

    response = client.get('/api/v1/employees/2222/registration-status')

    assert response.status_code == 200
    assert response.json()['authorization_exists'] is True
    assert response.json()['authorization_active'] is True
    assert response.json()['face_registered'] is True
    session.close()
    engine.dispose()


def test_status_lookup_returns_404_for_unknown_employee():
    client, session, engine = make_client()

    response = client.get('/api/v1/employees/4040/registration-status')

    assert response.status_code == 404
    assert 'not found' in response.json()['detail'].lower()
    session.close()
    engine.dispose()
