import { useState } from 'react';
import { CheckCircle2, ImageUp, ScanFace, Video } from 'lucide-react';
import { enrollFace } from '../../api/employees.js';
import useApiAction from '../../hooks/useApiAction.js';
import useCapturedFrames from '../../hooks/useCapturedFrames.js';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import ImageEnrollmentPanel, { SLOTS } from './ImageEnrollmentPanel.jsx';
import VideoEnrollmentPanel from './VideoEnrollmentPanel.jsx';

const ERROR_OVERRIDES = {
  404: 'Employee or authorization not found. Complete the previous steps first.',
  413: 'An uploaded image is too large.',
};
// Backend contract: POST /face-enrollment accepts 1-3 images (face_enrollment.MAX_ENROLLMENT_IMAGES).
const MAX_IMAGES = 3;
const MODES = { IMAGE: 'image', VIDEO: 'video' };

const tab = (active) =>
  `inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium disabled:opacity-50 ${
    active ? 'bg-brand text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
  }`;

export default function FaceEnrollmentForm({ employeeId, onEnrolled }) {
  const [mode, setMode] = useState(MODES.IMAGE);
  const [source, setSource] = useState(CAMERA_KINDS.WEBCAM);
  const [files, setFiles] = useState({ front: null, left: null, right: null });
  const [formError, setFormError] = useState(null);
  const captured = useCapturedFrames();
  const { run, loading, error, data } = useApiAction(
    (images) => enrollFace(employeeId, images),
    ERROR_OVERRIDES,
  );
  const locked = loading || !!data;
  const isImage = mode === MODES.IMAGE;

  const submit = async (event) => {
    event.preventDefault();
    let images;
    if (isImage) {
      if (!files.front) return setFormError('A front-facing image is required.');
      images = SLOTS.map((s) => files[s.key]).filter(Boolean);
    } else {
      images = (captured.frames[source] ?? []).map((f) => f.file);
      if (images.length === 0) return setFormError('Capture at least one face image before enrolling.');
    }
    setFormError(null);
    const result = await run(images.slice(0, MAX_IMAGES));
    if (result) onEnrolled?.(result);
    return undefined;
  };

  const changeMode = (next) => {
    setFormError(null);
    setMode(next);
  };

  return (
    <Card title="Face Enrollment">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <p className="text-sm text-slate-600">
          Provide clear photos from different angles. Each image must contain exactly one face.
          Liveness is not required during registration.
        </p>
        <div role="group" aria-label="Enrollment mode" className="flex flex-wrap gap-2">
          <button type="button" className={tab(isImage)} aria-pressed={isImage} disabled={locked}
            onClick={() => changeMode(MODES.IMAGE)}>
            <ImageUp className="h-4 w-4" aria-hidden /> Image Enrollment
          </button>
          <button type="button" className={tab(!isImage)} aria-pressed={!isImage} disabled={locked}
            onClick={() => changeMode(MODES.VIDEO)}>
            <Video className="h-4 w-4" aria-hidden /> Video Enrollment
          </button>
        </div>

        {isImage ? (
          <ImageEnrollmentPanel
            files={files}
            disabled={locked}
            onChange={(key, file) => setFiles((prev) => ({ ...prev, [key]: file }))}
          />
        ) : (
          <VideoEnrollmentPanel
            source={source}
            onSourceChange={setSource}
            frames={captured.frames}
            maxFrames={MAX_IMAGES}
            disabled={locked}
            onCapture={captured.add}
            onRemove={captured.remove}
          />
        )}

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
