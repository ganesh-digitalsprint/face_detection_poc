import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, CheckCircle2, ImageUp, ScanFace, Trash2, Video } from 'lucide-react';
import { enrollFace } from '../../api/employees.js';
import useApiAction from '../../../../hooks/useApiAction.js';
import useCapturedFrames from '../../hooks/useCapturedFrames.js';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import Button from '../../../../components/common/Button.jsx';
import Card from '../../../../components/common/Card.jsx';
import ErrorMessage from '../../../../components/common/ErrorMessage.jsx';
import ImageEnrollmentPanel, { SLOTS } from './ImageEnrollmentPanel.jsx';
import VideoEnrollmentPanel from './VideoEnrollmentPanel.jsx';

const ERROR_OVERRIDES = {
  404: 'Employee or authorization not found. Complete the previous steps first.',
  413: 'An uploaded image is too large.',
};
// Backend contract: POST /face-enrollment accepts 1-3 images (face_enrollment.MAX_ENROLLMENT_IMAGES).
const MAX_IMAGES = 3;
const MODES = { IMAGE: 'image', VIDEO: 'video' };
const DUPLICATE_CODE = 'FACE_ALREADY_ENROLLED';
const DIFFERENT_PEOPLE_CODE = 'IMAGES_NOT_SAME_PERSON';
const DUPLICATE_BACKEND_MESSAGE = 'This face is already enrolled under another employee.';

const tab = (active) =>
  `inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium disabled:opacity-50 ${
    active ? 'bg-brand text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
  }`;

export default function FaceEnrollmentForm({ employeeId, onEnrolled }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState(MODES.IMAGE);
  const [source, setSource] = useState(CAMERA_KINDS.WEBCAM);
  const [files, setFiles] = useState({ front: null, left: null, right: null });
  const [formError, setFormError] = useState(null);
  const captured = useCapturedFrames();
  const { run, loading, error, data, reset } = useApiAction(
    (images) => enrollFace(employeeId, images),
    ERROR_OVERRIDES,
  );
  const locked = loading || !!data;
  const isImage = mode === MODES.IMAGE;
  const isDuplicateFace = error?.code === DUPLICATE_CODE;
  const isDifferentPeople = error?.code === DIFFERENT_PEOPLE_CODE;

  const clearUploadError = () => {
    setFormError(null);
    if (error) reset();
  };

  const submit = async (event) => {
    event.preventDefault();
    if (isDifferentPeople || isDuplicateFace) return;
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
    if (error && !isDuplicateFace && !isDifferentPeople) reset();
    setMode(next);
  };

  const removeCurrentImages = () => {
    clearUploadError();
    if (isImage) {
      setFiles({ front: null, left: null, right: null });
      return;
    }
    for (const frame of captured.frames[source] ?? []) captured.remove(source, frame.id);
  };

  const duplicateDetail = error?.message !== DUPLICATE_BACKEND_MESSAGE ? error?.message : null;

  return (
    <Card title="Face Enrollment">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <p className="text-sm text-slate-600">
          Provide clear photos from different angles. Each image must contain exactly one face.
          Liveness is not required during registration.
        </p>
        <div role="group" aria-label="Enrollment mode" className="flex flex-wrap gap-2">
          <button type="button" className={tab(isImage)} aria-pressed={isImage} disabled={locked || isDuplicateFace || isDifferentPeople}
            onClick={() => changeMode(MODES.IMAGE)}>
            <ImageUp className="h-4 w-4" aria-hidden /> Image Enrollment
          </button>
          <button type="button" className={tab(!isImage)} aria-pressed={!isImage} disabled={locked || isDuplicateFace || isDifferentPeople}
            onClick={() => changeMode(MODES.VIDEO)}>
            <Video className="h-4 w-4" aria-hidden /> Video Enrollment
          </button>
        </div>

        {isImage ? (
          <ImageEnrollmentPanel
            files={files}
            disabled={locked}
            onChange={(key, file) => {
              clearUploadError();
              setFiles((prev) => ({ ...prev, [key]: file }));
            }}
          />
        ) : (
          <VideoEnrollmentPanel
            source={source}
            onSourceChange={setSource}
            frames={captured.frames}
            maxFrames={MAX_IMAGES}
            disabled={locked}
            onCapture={(...args) => { clearUploadError(); captured.add(...args); }}
            onRemove={(...args) => { clearUploadError(); captured.remove(...args); }}
          />
        )}

        <ErrorMessage error={formError} />
        {isDuplicateFace ? (
          <div role="alert" className="flex items-start gap-3 rounded-lg border border-[#F3C7C3] bg-[#FDE9E7] p-4 text-sm text-[#B3261E]">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
            <div className="space-y-1">
              <h3 className="font-bold">Face already registered</h3>
              <p>This face is already enrolled under another employee. A person can only have one employee ID. Check the employee ID or contact an administrator.</p>
              {duplicateDetail && <p className="pt-1 text-xs">{duplicateDetail}</p>}
            </div>
          </div>
        ) : isDifferentPeople ? (
          <div role="alert" className="flex items-start gap-3 rounded-lg border border-[#F3C7C3] bg-[#FDE9E7] p-4 text-sm text-[#B3261E]">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
            <p>These images do not appear to show the same person. Remove the image that is different and try again.</p>
          </div>
        ) : <ErrorMessage error={error} />}
        {data ? (
          <p role="status" className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
            <CheckCircle2 className="h-5 w-5" aria-hidden /> {data.images_enrolled} image(s) enrolled
          </p>
        ) : (
          isDuplicateFace ? (
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" icon={Trash2} disabled={locked} onClick={removeCurrentImages} className="min-h-11">
                Remove images
              </Button>
              <Button variant="secondary" icon={ArrowLeft} disabled={locked}
                onClick={() => navigate(`/registration/authorized/${encodeURIComponent(employeeId)}`)} className="min-h-11">
                Back
              </Button>
            </div>
          ) : (
            <Button type="submit" icon={ScanFace} loading={loading} disabled={isDifferentPeople} className="min-h-11">
              {loading ? 'Enrolling face...' : 'Enroll Face'}
            </Button>
          )
        )}
      </form>
    </Card>
  );
}
