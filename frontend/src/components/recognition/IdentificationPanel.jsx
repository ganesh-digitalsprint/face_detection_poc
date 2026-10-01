import { useState } from 'react';
import { ScanSearch, Users } from 'lucide-react';
import { identifyFaces } from '../../api/recognition.js';
import useApiAction from '../../hooks/useApiAction.js';
import useObjectUrl from '../../hooks/useObjectUrl.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import EmptyState from '../common/EmptyState.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import Loading from '../common/Loading.jsx';
import FaceBoundingBoxViewer from '../face/FaceBoundingBoxViewer.jsx';
import ImageUploader from '../face/ImageUploader.jsx';
import RecognitionResult from './RecognitionResult.jsx';

export default function IdentificationPanel() {
  const [file, setFile] = useState(null);
  const [analyzed, setAnalyzed] = useState(null); // file the current result belongs to
  const url = useObjectUrl(analyzed);
  const { run, loading, error, data, reset } = useApiAction(identifyFaces);

  const change = (next) => {
    setFile(next);
    setAnalyzed(null);
    reset();
  };

  const submit = async () => {
    if (!file) return;
    const result = await run(file);
    if (result) setAnalyzed(file);
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Upload Image">
        <p className="mb-3 text-sm text-slate-500">Upload an image containing one or more faces.</p>
        <div className="space-y-4">
          <ImageUploader file={file} onChange={change} disabled={loading} label="Image" />
          <Button icon={ScanSearch} loading={loading} disabled={!file} onClick={submit}>Identify Faces</Button>
        </div>
      </Card>

      <Card title="Identification Results">
        {loading && <Loading message="Identifying faces..." />}
        <ErrorMessage error={error} />
        {data && (
          <div className="space-y-4">
            <p className="text-sm font-semibold text-slate-700">
              Faces detected: {data.faces_detected}
              <span className="ml-2 text-xs font-normal text-slate-400">{data.processing_time_ms.toFixed(0)} ms</span>
            </p>
            {url && (
              <FaceBoundingBoxViewer
                src={url}
                alt="Analyzed image with identified faces"
                faces={data.recognized_faces.map((r, i) => ({
                  bbox: r.bbox,
                  label: r.matched ? `${r.person_code}` : `#${i + 1} Unknown`,
                  tone: r.matched ? 'match' : 'unknown',
                }))}
              />
            )}
            {data.faces_detected === 0 ? (
              <EmptyState icon={Users} title="No faces detected" />
            ) : (
              <ul className="space-y-3">
                {data.recognized_faces.map((r, i) => <RecognitionResult key={i} result={r} index={i} />)}
              </ul>
            )}
          </div>
        )}
        {!loading && !error && !data && <EmptyState icon={Users} title="No results yet" description="Upload an image and click Identify Faces." />}
      </Card>
    </div>
  );
}
