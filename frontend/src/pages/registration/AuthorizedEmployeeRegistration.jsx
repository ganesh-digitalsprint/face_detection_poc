import { useParams } from 'react-router-dom';
import AuthorizationForm from '../../components/registration/AuthorizationForm.jsx';
import EmployeeSummary from '../../components/registration/EmployeeSummary.jsx';
import RegistrationProgress from '../../components/registration/RegistrationProgress.jsx';
import { findEmployee } from '../../utils/employeeDirectory.js';

export default function AuthorizedEmployeeRegistration() {
  const { employeeId } = useParams();
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <RegistrationProgress current={1} />
      <EmployeeSummary employeeId={employeeId} employee={findEmployee(employeeId)} />
      <AuthorizationForm employeeId={employeeId} />
    </div>
  );
}
