import { useState } from 'react';
import { ArrowRight, CheckCircle2, UserPlus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { createEmployee } from '../../api/employees.js';
import useApiAction from '../../hooks/useApiAction.js';
import { rememberEmployee } from '../../utils/employeeDirectory.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';

const ERROR_OVERRIDES = { 409: 'An employee with this Employee ID already exists.' };
const EMPTY = { employee_id: '', name: '', department: '', designation: '' };
const inputCls = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand disabled:bg-slate-50';

// Mirrors backend EmployeeCreate length limits.
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
  const { run, loading, error, data } = useApiAction(createEmployee, ERROR_OVERRIDES);
  const set = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));
  const locked = loading || !!data;

  const submit = async (event) => {
    event.preventDefault();
    const problem = validate(form);
    setFormError(problem);
    if (problem) return;
    const optional = (value) => value.trim() || null;
    const created = await run({
      employee_id: form.employee_id.trim(),
      name: form.name.trim(),
      department: optional(form.department),
      designation: optional(form.designation),
    });
    if (created) rememberEmployee(created);
  };

  const next = () => navigate(`/registration/authorized/${encodeURIComponent(data.employee_id)}`);

  return (
    <Card title="Employee Details">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field id="employee_id" label="Employee ID" required value={form.employee_id} placeholder="EMP001" disabled={locked} onChange={set('employee_id')} />
        <Field id="employee_name" label="Name" required value={form.name} placeholder="Full name" disabled={locked} onChange={set('name')} />
        <Field id="department" label="Department" value={form.department} disabled={locked} onChange={set('department')} />
        <Field id="designation" label="Designation" value={form.designation} disabled={locked} onChange={set('designation')} />
        <ErrorMessage error={formError} />
        <ErrorMessage error={error} />
        {data ? (
          <div role="status" className="space-y-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
              <CheckCircle2 className="h-5 w-5" aria-hidden /> Employee registered: {data.employee_id} · {data.name}
            </p>
            <Button icon={ArrowRight} onClick={next}>Continue to Authorization</Button>
          </div>
        ) : (
          <Button type="submit" icon={UserPlus} loading={loading}>Register Employee</Button>
        )}
      </form>
    </Card>
  );
}
