import { useState } from 'react';
import { CheckCircle2, ScanFace } from 'lucide-react';
import { enrollFace } from '../../api/employees.js';
import useApiAction from '../../hooks/useApiAction.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import ImageUploader from '../face/ImageUploader.jsx';

const ERROR_OVERRIDES = {
  404: 'Employee or authorization not found. Complete the previous steps first.',
  413: 'An uploaded image is too large.',
};
const SLOTS = [
  { key: 'front', label: 'Front Face (required)' },
  { key: 'left', label: 'Left Angle (recommended)' },
  { key: 'right', label: 'Right Angle (recommended)' },
];

export default function FaceEnrollmentForm({ employeeId, onEnrolled }) {
  const [files, setFiles] = useState({ front: null, left: null, right: null });
  const [formError, setFormError] = useState(null);
  const { run, loading, error, data } = useApiAction(
    (images) => enrollFace(employeeId, images),
    ERROR_OVERRIDES,
  );
  const locked = loading || !!data;

  const submit = async (event) => {
    event.preventDefault();
    if (!files.front) return setFormError('A front-facing image is required.');
    setFormError(null);
    const result = await run(SLOTS.map((s) => files[s.key]).filter(Boolean));
    if (result) onEnrolled?.(result);
    return undefined;
  };

  return (
    <Card title="Face Enrollment">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <p className="text-sm text-slate-600">
          Provide clear photos from different angles. Each image must contain exactly one face.
          Liveness is not required during registration.
        </p>
        <div className="grid gap-4 md:grid-cols-3">
          {SLOTS.map((slot) => (
            <ImageUploader
              key={slot.key}
              label={slot.label}
              file={files[slot.key]}
              disabled={locked}
              onChange={(file) => setFiles((prev) => ({ ...prev, [slot.key]: file }))}
            />
          ))}
        </div>
        <ErrorMessage error={formError} />
        <ErrorMessage error={error} />
        {data ? (
          <p role="status" className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
            <CheckCircle2 className="h-5 w-5" aria-hidden /> {data.images_enrolled} image(s) enrolled
          </p>
        ) : (
          <Button type="submit" icon={ScanFace} loading={loading}>
            {loading ? 'Enrolling face...' : 'Enroll Face'}
          </Button>
        )}
      </form>
    </Card>
  );
}
