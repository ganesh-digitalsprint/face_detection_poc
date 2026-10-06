import { useState } from 'react';
import { ArrowRight, CheckCircle2, ShieldPlus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { createAuthorization } from '../../api/employees.js';
import useApiAction from '../../hooks/useApiAction.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';

const ERROR_OVERRIDES = {
  404: 'Employee not found. Register the employee first.',
  409: 'Authorization already exists for this employee.',
};
const inputCls = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand disabled:bg-slate-50';

export default function AuthorizationForm({ employeeId }) {
  const navigate = useNavigate();
  const [isActive, setIsActive] = useState(true);
  const [reason, setReason] = useState('');
  const [authorizedBy, setAuthorizedBy] = useState('');
  const [remarks, setRemarks] = useState('');
  const [formError, setFormError] = useState(null);
  const { run, loading, error, data } = useApiAction(
    (payload) => createAuthorization(employeeId, payload),
    ERROR_OVERRIDES,
  );
  const locked = loading || !!data;

  const submit = async (event) => {
    event.preventDefault();
    if (authorizedBy.trim().length > 50) return setFormError('Authorized By may be at most 50 characters.');
    setFormError(null);
    return run({
      is_active: isActive,
      authorization_reason: reason.trim() || null,
      authorized_by: authorizedBy.trim() || null,
      remarks: remarks.trim() || null,
    });
  };

  const next = () => navigate(`/registration/authorized/${encodeURIComponent(employeeId)}/face`);

  return (
    <Card title="Vault Authorization">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <label className="flex items-center gap-3 text-sm font-medium text-slate-700">
          <input type="checkbox" className="h-4 w-4" checked={isActive} disabled={locked} onChange={(e) => setIsActive(e.target.checked)} />
          Authorization Status: {isActive ? 'ACTIVE' : 'INACTIVE'}
        </label>
        <div>
          <label htmlFor="auth_reason" className="mb-1 block text-sm font-medium text-slate-700">Authorization Reason</label>
          <input id="auth_reason" className={inputCls} value={reason} disabled={locked} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div>
          <label htmlFor="authorized_by" className="mb-1 block text-sm font-medium text-slate-700">Authorized By</label>
          <input id="authorized_by" className={inputCls} value={authorizedBy} disabled={locked} onChange={(e) => setAuthorizedBy(e.target.value)} />
        </div>
        <div>
          <label htmlFor="remarks" className="mb-1 block text-sm font-medium text-slate-700">Remarks</label>
          <textarea id="remarks" rows={3} className={inputCls} value={remarks} disabled={locked} onChange={(e) => setRemarks(e.target.value)} />
        </div>
        <ErrorMessage error={formError} />
        <ErrorMessage error={error} />
        {data ? (
          <div role="status" className="space-y-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
              <CheckCircle2 className="h-5 w-5" aria-hidden /> Authorization registered ({data.is_active ? 'ACTIVE' : 'INACTIVE'})
            </p>
            <Button icon={ArrowRight} onClick={next}>Continue to Face Enrollment</Button>
          </div>
        ) : (
          <Button type="submit" icon={ShieldPlus} loading={loading}>Register Authorization</Button>
        )}
      </form>
    </Card>
  );
}
