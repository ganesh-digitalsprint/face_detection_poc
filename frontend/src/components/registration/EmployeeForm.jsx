import { useState } from 'react';
import { ArrowRight, CheckCircle2, Search, UserPlus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { createEmployee, getEmployeeRegistrationStatus } from '../../api/employees.js';
import { describeError } from '../../utils/errors.js';
import { rememberEmployee } from '../../utils/employeeDirectory.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';

const ERROR_OVERRIDES = {
  409: 'An employee with this Employee ID already exists. The existing record has been loaded below.',
};
const EMPTY = { employee_id: '', name: '', department: '', designation: '' };
const inputCls = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand disabled:bg-slate-50';

function validate(form) {
  if (!form.employee_id.trim()) return 'Employee ID is required.';
  if (form.employee_id.trim().length > 50) return 'Employee ID may be at most 50 characters.';
  if (!form.name.trim()) return 'Name is required.';
  if (form.name.trim().length > 150) return 'Name may be at most 150 characters.';
  if (form.department.trim().length > 100) return 'Department may be at most 100 characters.';
  if (form.designation.trim().length > 100) return 'Designation may be at most 100 characters.';
  return null;
}

const Field = ({ id, label, required, ...props }) => (
  <div>
    <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
      {label}{required && <span className="text-red-600"> *</span>}
    </label>
    <input id={id} className={inputCls} {...props} />
  </div>
);

export default function EmployeeForm() {
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY);
  const [formError, setFormError] = useState(null);
  const [apiError, setApiError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [created, setCreated] = useState(null);
  const [existing, setExisting] = useState(null);
  const locked = loading || !!created || !!existing;

  const set = (key) => (event) => {
    setForm((prev) => ({ ...prev, [key]: event.target.value }));
    setCreated(null);
    setExisting(null);
    setApiError(null);
  };

  const submit = async (event) => {
    event.preventDefault();
    const problem = validate(form);
    setFormError(problem);
    if (problem || loading) return;

    const employeeId = form.employee_id.trim();
    const payload = {
      employee_id: employeeId,
      name: form.name.trim(),
      department: form.department.trim() || null,
      designation: form.designation.trim() || null,
    };
    setLoading(true);
    setApiError(null);
    setCreated(null);
    setExisting(null);
    try {
      try {
        const status = await getEmployeeRegistrationStatus(employeeId);
        setExisting(status);
        return;
      } catch (lookupError) {
        if (lookupError?.response?.status !== 404) throw lookupError;
      }

      try {
        const employee = await createEmployee(payload);
        rememberEmployee(employee);
        setCreated(employee);
      } catch (createError) {
        // Cover a second administrator creating this ID between the lookup and POST.
        if (createError?.response?.status !== 409) throw createError;
        const status = await getEmployeeRegistrationStatus(employeeId);
        setExisting(status);
      }
    } catch (requestError) {
      setApiError(describeError(requestError, ERROR_OVERRIDES));
    } finally {
      setLoading(false);
    }
  };

  const findExisting = async () => {
    const employeeId = form.employee_id.trim();
    if (!employeeId) return setFormError('Employee ID is required to look up an existing employee.');
    if (employeeId.length > 50) return setFormError('Employee ID may be at most 50 characters.');
    setFormError(null);
    setApiError(null);
    setLoading(true);
    try {
      const status = await getEmployeeRegistrationStatus(employeeId);
      setExisting(status);
    } catch (lookupError) {
      setApiError(lookupError?.response?.status === 404
        ? { status: 404, message: 'No employee with this ID is registered yet.' }
        : describeError(lookupError));
    } finally {
      setLoading(false);
    }
  };

  const openNextStep = (employeeId, authorizationExists) => {
    const encodedId = encodeURIComponent(employeeId);
    navigate(authorizationExists
      ? `/registration/authorized/${encodedId}/face`
      : `/registration/authorized/${encodedId}`);
  };

  const startOver = () => {
    setForm(EMPTY);
    setCreated(null);
    setExisting(null);
    setApiError(null);
    setFormError(null);
  };

  return (
    <Card title="Employee Details">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field id="employee_id" label="Employee ID" required value={form.employee_id} placeholder="EMP001" disabled={locked} onChange={set('employee_id')} />
        <Field id="employee_name" label="Name" required value={form.name} placeholder="Full name" disabled={locked} onChange={set('name')} />
        <Field id="department" label="Department" value={form.department} disabled={locked} onChange={set('department')} />
        <Field id="designation" label="Designation" value={form.designation} disabled={locked} onChange={set('designation')} />
        <ErrorMessage error={formError} />
        <ErrorMessage error={apiError} />

        {created && (
          <div role="status" className="space-y-3 rounded-md border border-emerald-200 bg-emerald-50 p-4">
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
              <CheckCircle2 className="h-5 w-5" aria-hidden /> Employee registered: {created.employee_id} · {created.name}
            </p>
            <p className="text-sm text-slate-700">Employee registration is complete. Authorization and face enrollment are separate steps you can do now or later.</p>
            <div className="flex flex-wrap gap-2">
              <Button icon={ArrowRight} onClick={() => openNextStep(created.employee_id, false)}>Continue to Authorization</Button>
              <Button variant="secondary" onClick={startOver}>Finish for now</Button>
            </div>
          </div>
        )}

        {existing && (
          <div role="status" className="space-y-3 rounded-md border border-blue-200 bg-blue-50 p-4">
            <p className="flex items-center gap-2 text-sm font-semibold text-navy">
              <CheckCircle2 className="h-5 w-5" aria-hidden /> Employee already registered: {existing.employee_id}
            </p>
            <ul className="space-y-1 text-sm text-slate-700">
              <li>Authorization: {existing.authorization_exists ? (existing.authorization_active ? 'Active' : 'Inactive') : 'Not registered'}</li>
              <li>Face enrollment: {existing.face_registered ? 'Complete' : 'Not complete'}</li>
            </ul>
            <div className="flex flex-wrap gap-2">
              <Button icon={ArrowRight} onClick={() => openNextStep(existing.employee_id, existing.authorization_exists)}>
                {existing.authorization_exists
                  ? (existing.face_registered ? 'Open Face Enrollment' : 'Continue to Face Enrollment')
                  : 'Continue to Authorization'}
              </Button>
              <Button variant="secondary" onClick={startOver}>Look up another employee</Button>
            </div>
          </div>
        )}

        {!created && !existing && (
          <div className="flex flex-wrap gap-2">
            <Button type="submit" icon={UserPlus} loading={loading}>
              {loading ? 'Checking employee ID...' : 'Register Employee'}
            </Button>
            <Button type="button" variant="secondary" icon={Search} disabled={loading} onClick={findExisting}>
              Find Existing Employee
            </Button>
          </div>
        )}
      </form>
    </Card>
  );
}
