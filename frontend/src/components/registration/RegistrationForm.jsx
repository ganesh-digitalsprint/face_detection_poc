import { useState } from 'react';
import { CheckCircle2, UserPlus } from 'lucide-react';
import { registerPerson } from '../../api/persons.js';
import useApiAction from '../../hooks/useApiAction.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import Loading from '../common/Loading.jsx';
import ImageUploader from '../face/ImageUploader.jsx';

const ERROR_OVERRIDES = {
  409: 'This person code already exists.',
  413: 'The uploaded image is too large.',
};
// Mirrors backend PersonCode: letters, digits, underscore, dot, hyphen; max 64.
const CODE_PATTERN = /^[A-Za-z0-9_.-]+$/;

const inputCls = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand';

export default function RegistrationForm() {
  const [personCode, setPersonCode] = useState('');
  const [name, setName] = useState('');
  const [file, setFile] = useState(null);
  const [formError, setFormError] = useState(null);
  const { run, loading, error, data, reset } = useApiAction(
    (code, personName, image) => registerPerson(code, personName, image),
    ERROR_OVERRIDES,
  );

  const submit = async (event) => {
    event.preventDefault();
    const code = personCode.trim();
    const trimmedName = name.trim();
    if (!code) return setFormError('Person code is required.');
    if (code.length > 64 || !CODE_PATTERN.test(code)) {
      return setFormError('Person code may contain only letters, digits, "_", "." and "-" (max 64).');
    }
    if (!trimmedName) return setFormError('Name is required.');
    if (!file) return setFormError('A face image is required.');
    setFormError(null);
    const result = await run(code, trimmedName, file);
    if (result) {
      setPersonCode('');
      setName('');
      setFile(null);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Register Person">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="person_code" className="mb-1 block text-sm font-medium text-slate-700">Person Code</label>
            <input id="person_code" className={inputCls} value={personCode} placeholder="P001" disabled={loading}
              onChange={(e) => setPersonCode(e.target.value)} />
          </div>
          <div>
            <label htmlFor="person_name" className="mb-1 block text-sm font-medium text-slate-700">Name</label>
            <input id="person_name" className={inputCls} value={name} placeholder="John Doe" disabled={loading}
              onChange={(e) => setName(e.target.value)} />
          </div>
          <ImageUploader file={file} onChange={setFile} disabled={loading} label="Face Image (exactly one face)" />
          <ErrorMessage error={formError} />
          <Button type="submit" icon={UserPlus} loading={loading}>Register Person</Button>
        </form>
      </Card>

      <Card title="Result">
        {loading && <Loading message="Registering face..." />}
        <ErrorMessage error={error} />
        {data && (
          <div className="space-y-2 text-sm" role="status">
            <p className="flex items-center gap-2 font-semibold text-emerald-700">
              <CheckCircle2 className="h-5 w-5" aria-hidden /> Person Registered
            </p>
            <dl className="grid grid-cols-[8rem_1fr] gap-y-1">
              <dt className="text-slate-500">Person ID</dt><dd>{data.person_id}</dd>
              <dt className="text-slate-500">Person Code</dt><dd>{data.person_code}</dd>
              <dt className="text-slate-500">Name</dt><dd>{data.name}</dd>
              <dt className="text-slate-500">Face</dt><dd>{data.face_registered ? 'Enrolled' : 'Not enrolled'}</dd>
              <dt className="text-slate-500">Model</dt><dd>{data.model_name}</dd>
            </dl>
            <Button variant="secondary" onClick={reset}>Register another</Button>
          </div>
        )}
        {!loading && !error && !data && <p className="text-sm text-slate-500">Submit the form to enroll a person.</p>}
      </Card>
    </div>
  );
}
