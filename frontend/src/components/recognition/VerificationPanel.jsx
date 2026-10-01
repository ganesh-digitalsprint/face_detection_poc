import { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { verifyFace } from '../../api/recognition.js';
import useApiAction from '../../hooks/useApiAction.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import Loading from '../common/Loading.jsx';
import StatusBadge from '../common/StatusBadge.jsx';
import ImageUploader from '../face/ImageUploader.jsx';
import { formatScore } from '../../utils/formatters.js';

const ERROR_OVERRIDES = {
  400: 'Image must contain exactly one face.',
  404: 'Person code not found.',
  409: 'Person does not have an active enrolled face.',
  413: 'The uploaded image is too large.',
};

export default function VerificationPanel() {
  const [personCode, setPersonCode] = useState('');
  const [file, setFile] = useState(null);
  const [formError, setFormError] = useState(null);
  const [checkedCode, setCheckedCode] = useState('');
  const { run, loading, error, data, reset } = useApiAction(verifyFace, ERROR_OVERRIDES);

  const submit = async (event) => {
    event.preventDefault();
    const code = personCode.trim();
    if (!code) return setFormError('Person code is required.');
    if (!file) return setFormError('A face image is required.');
    setFormError(null);
    setCheckedCode(code);
    await run(code, file);
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Verify Identity (1:1)">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="verify_code" className="mb-1 block text-sm font-medium text-slate-700">Person Code</label>
            <input id="verify_code" value={personCode} placeholder="P001" disabled={loading}
              onChange={(e) => { setPersonCode(e.target.value); reset(); }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand" />
          </div>
          <ImageUploader file={file} onChange={(f) => { setFile(f); reset(); }} disabled={loading} />
          <ErrorMessage error={formError} />
          <Button type="submit" icon={ShieldCheck} loading={loading}>Verify Identity</Button>
        </form>
      </Card>

      <Card title="Verification Result">
        {loading && <Loading message="Verifying..." />}
        <ErrorMessage error={error} />
        {data && (
          <div className="space-y-3 text-sm" role="status">
            <p>Person: <span className="font-semibold">{checkedCode}</span></p>
            <StatusBadge status={data.matched ? 'VERIFIED' : 'NOT VERIFIED'} />
            <dl className="grid grid-cols-[9rem_1fr] gap-y-1">
              <dt className="text-slate-500">Similarity Score</dt><dd>{formatScore(data.similarity)}</dd>
              <dt className="text-slate-500">Distance</dt><dd>{formatScore(data.distance)}</dd>
              <dt className="text-slate-500">Threshold</dt><dd>{formatScore(data.threshold)} <span className="text-xs text-slate-400">(max distance for a match)</span></dd>
            </dl>
            <p className="text-xs text-slate-400">Scores are not probabilities.</p>
          </div>
        )}
        {!loading && !error && !data && <p className="text-sm text-slate-500">Enter a person code and upload a face to verify.</p>}
      </Card>
    </div>
  );
}
