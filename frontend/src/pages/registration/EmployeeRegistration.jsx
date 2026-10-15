import EmployeeForm from '../../components/registration/EmployeeForm.jsx';

export default function EmployeeRegistration() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <p className="text-sm text-slate-600">Register an employee independently. You can add authorization and face enrollment now or return to them later.</p>
      <EmployeeForm />
    </div>
  );
}
