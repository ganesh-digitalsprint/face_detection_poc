"""Look up employee registration progress without creating duplicate records."""

from app.db.authorization_repository import AuthorizedEmployeeRepository
from app.db.employee_repositories import EmployeeRepository
from app.schemas.employee import EmployeeRegistrationStatus
from app.services.authorization_registration import EmployeeNotFoundError


class EmployeeLookupService:
    def __init__(
        self,
        employees: EmployeeRepository,
        authorizations: AuthorizedEmployeeRepository,
    ) -> None:
        self._employees = employees
        self._authorizations = authorizations

    def get_registration_status(self, employee_id: str) -> EmployeeRegistrationStatus:
        employee = self._employees.get_by_employee_id(employee_id.strip())
        if employee is None:
            raise EmployeeNotFoundError(f"Employee '{employee_id}' was not found")

        authorization = self._authorizations.get_for_employee(employee.id)
        return EmployeeRegistrationStatus(
            employee_id=employee.employee_id,
            authorization_exists=authorization is not None,
            authorization_active=authorization.is_active if authorization else None,
            face_registered=authorization.face_registered if authorization else False,
        )
