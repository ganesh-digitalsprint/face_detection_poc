import EmployeeForm from '../../components/registration/EmployeeForm.jsx';
import RegistrationProgress from '../../components/registration/RegistrationProgress.jsx';

export default function EmployeeRegistration() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <RegistrationProgress current={0} />
      <EmployeeForm />
    </div>
  );
}
