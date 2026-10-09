import { useState } from 'react';
import { CheckCircle2, Cctv, ImageUp, ScanFace, Webcam, X } from 'lucide-react';
import { registerPersonFromImages } from '../../api/persons.js';
import useApiAction from '../../hooks/useApiAction.js';
import useCameraSource, { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import useObjectUrl from '../../hooks/useObjectUrl.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import Loading from '../common/Loading.jsx';
import CameraPreview from '../vault/CameraPreview.jsx';
import ImageUploader from '../face/ImageUploader.jsx';

const ERROR_OVERRIDES = {
  409: 'This person code already exists.',
  413: 'An image is too large. Each image must be 10 MB or smaller.',
};
const CODE_PATTERN = /^[A-Za-z0-9_.-]+$/;
const MAX_IMAGES = 10;
const inputCls = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand';

function ImageTile({ file, index, disabled, onRemove }) {
  const preview = useObjectUrl(file);
  return (
    <div className="relative overflow-hidden rounded-md border border-slate-200 bg-slate-900">
      {preview && <img src={preview} alt={`Enrollment image ${index + 1}`} className="h-32 w-full object-contain" />}
      <button type="button" disabled={disabled} onClick={onRemove} aria-label={`Remove image ${index + 1}`}
        className="absolute right-1 top-1 rounded-full bg-white p-1 text-slate-700 shadow disabled:opacity-50">
        <X className="h-4 w-4" aria-hidden />
      </button>
      <p className="truncate bg-white px-2 py-1 text-xs text-slate-600">{file.name}</p>
    </div>
  );
}

export default function RegistrationForm() {
  const [personCode, setPersonCode] = useState('');
  const [name, setName] = useState('');
  const [files, setFiles] = useState([]);
  const [source, setSource] = useState('upload');
  const [formError, setFormError] = useState(null);
  const camera = useCameraSource();
  const { run, loading, error, data, reset } = useApiAction(
    (code, personName, images) => registerPersonFromImages(code, personName, images),
    ERROR_OVERRIDES,
  );
  const locked = loading || !!data;

  const chooseSource = (next) => {
    setFormError(null);
    camera.stop();
    setSource(next);
    if (next === 'upload') {
      return;
    }
  };

  const startWebcam = () => camera.start(CAMERA_KINDS.WEBCAM);

  const addFiles = (incoming) => {
    const candidates = Array.from(incoming ?? []);
    if (!candidates.length) return;
    if (files.length + candidates.length > MAX_IMAGES) {
      return setFormError(`You can register up to ${MAX_IMAGES} images.`);
    }
    setFormError(null);
    setFiles((current) => [...current, ...candidates]);
  };

  const capture = async () => {
    try {
      if (files.length >= MAX_IMAGES) return setFormError(`You can register up to ${MAX_IMAGES} images.`);
      const blob = await camera.captureFrame();
      setFiles((current) => [...current, new File([blob], `capture-${Date.now()}.jpg`, { type: 'image/jpeg' })]);
      setFormError(null);
    } catch (captureError) {
      setFormError(captureError.message || 'Could not capture this frame.');
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    const code = personCode.trim();
    const trimmedName = name.trim();
    if (!code) return setFormError('Person code is required.');
    if (code.length > 64 || !CODE_PATTERN.test(code)) {
      return setFormError('Person code may contain only letters, digits, "_", "." and "-" (max 64).');
    }
    if (!trimmedName) return setFormError('Name is required.');
    if (!files.length) return setFormError('Add at least one face image before registering.');
    setFormError(null);
    const result = await run(code, trimmedName, files);
    if (result) {
      camera.stop();
      setPersonCode('');
      setName('');
      setFiles([]);
    }
  };

  const startAnother = () => {
    reset();
    setPersonCode('');
    setName('');
    setFiles([]);
    setFormError(null);
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Register Person">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="person_code" className="mb-1 block text-sm font-medium text-slate-700">Person Code</label>
            <input id="person_code" className={inputCls} value={personCode} placeholder="P001" disabled={locked}
              onChange={(e) => setPersonCode(e.target.value)} />
          </div>
          <div>
            <label htmlFor="person_name" className="mb-1 block text-sm font-medium text-slate-700">Name</label>
            <input id="person_name" className={inputCls} value={name} placeholder="John Doe" disabled={locked}
              onChange={(e) => setName(e.target.value)} />
          </div>

          <div>
            <p className="mb-2 text-sm font-medium text-slate-700">Image source</p>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Registration image source">
              <button type="button" disabled={locked} aria-pressed={source === 'upload'} onClick={() => chooseSource('upload')}
                className={`rounded-md border px-3 py-2 text-sm ${source === 'upload' ? 'border-brand bg-blue-50 text-brand' : 'border-slate-300'}`}>
                <ImageUp className="mr-1 inline h-4 w-4" aria-hidden /> Upload Images
              </button>
              <button type="button" disabled={locked} aria-pressed={source === 'webcam'} onClick={() => chooseSource('webcam')}
                className={`rounded-md border px-3 py-2 text-sm ${source === 'webcam' ? 'border-brand bg-blue-50 text-brand' : 'border-slate-300'}`}>
                <Webcam className="mr-1 inline h-4 w-4" aria-hidden /> Capture from Webcam
              </button>
              <button type="button" disabled title="CCTV capture requires an authenticated admin access layer."
                className="rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-400">
                <Cctv className="mr-1 inline h-4 w-4" aria-hidden /> Capture from CCTV (unavailable)
              </button>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              CCTV registration needs a configured stream and an authenticated admin flow. This app does not yet provide that access check.
            </p>
          </div>

          {source === 'upload' && (
            <div>
              <ImageUploader file={null} onChange={addFiles} disabled={locked} multiple label="Choose face images" />
              <p className="mt-1 text-xs text-slate-500">Select up to {MAX_IMAGES} clear images. Each image must contain one face.</p>
            </div>
          )}

          {source !== 'upload' && (
            <>
              {camera.status === 'idle' && (
                <div className="rounded-md border border-slate-200 bg-slate-50 p-5 text-center">
                  <Webcam className="mx-auto h-8 w-8 text-slate-500" aria-hidden />
                  <p className="mt-2 text-sm text-slate-700">Start capturing face images from your webcam.</p>
                  <Button className="mt-3" icon={Webcam} onClick={startWebcam}>Start Camera</Button>
                </div>
              )}
              {camera.status !== 'idle' && <CameraPreview camera={camera} />}
              {camera.status === 'error' && <Button variant="secondary" onClick={startWebcam}>Retry Camera</Button>}
              {camera.status === 'ready' && (
                <div className="flex gap-2">
                  <Button icon={ScanFace} disabled={locked} onClick={capture}>Capture Image</Button>
                  <Button variant="secondary" disabled={locked} onClick={camera.stop}>Stop Camera</Button>
                </div>
              )}
              {camera.status === 'ready' && (
                <p role="status" aria-live="polite" className="text-xs text-slate-600">Images captured: {files.length}</p>
              )}
              <p className="text-xs text-slate-500">Capture frontal, slight left and right turns, then return to frontal. You can add images from another source too.</p>
            </>
          )}

          <section aria-label="Selected enrollment images" className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-slate-700">Review images</p>
              <span className="text-xs text-slate-500">{files.length} / {MAX_IMAGES}</span>
            </div>
            {files.length ? (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {files.map((file, index) => (
                  <ImageTile key={`${file.name}-${index}`} file={file} index={index} disabled={locked}
                    onRemove={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))} />
                ))}
              </div>
            ) : <p className="text-xs text-slate-500">No images selected yet.</p>}
          </section>

          <ErrorMessage error={formError} />
          <ErrorMessage error={error} />
          <Button type="submit" icon={ScanFace} loading={loading} disabled={locked}>
            {loading ? 'Validating images, generating embeddings, and saving...' : 'Register Person'}
          </Button>
        </form>
      </Card>

      <Card title="Result">
        {loading && <Loading message="Validating images... Generating embeddings... Saving registration..." />}
        {data && (
          <div className="space-y-2 text-sm" role="status">
            <p className="flex items-center gap-2 font-semibold text-emerald-700">
              <CheckCircle2 className="h-5 w-5" aria-hidden /> Person Registered
            </p>
            <dl className="grid grid-cols-[8rem_1fr] gap-y-1">
              <dt className="text-slate-500">Person ID</dt><dd>{data.person_id}</dd>
              <dt className="text-slate-500">Person Code</dt><dd>{data.person_code}</dd>
              <dt className="text-slate-500">Name</dt><dd>{data.name}</dd>
              <dt className="text-slate-500">Face</dt><dd>{data.images_enrolled ?? 1} image(s) enrolled</dd>
              <dt className="text-slate-500">Model</dt><dd>{data.model_name}</dd>
            </dl>
            <Button variant="secondary" onClick={startAnother}>Register another</Button>
          </div>
        )}
        {!loading && !error && !data && <p className="text-sm text-slate-500">Add images and register a person.</p>}
      </Card>
    </div>
  );
}
