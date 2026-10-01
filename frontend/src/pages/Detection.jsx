import { useState } from 'react';
import { ScanFace } from 'lucide-react';
import { detectFaces, detectFacesAnnotated } from '../api/faces.js';
import Button from '../components/common/Button.jsx';
import Card from '../components/common/Card.jsx';
import EmptyState from '../components/common/EmptyState.jsx';
import ErrorMessage from '../components/common/ErrorMessage.jsx';
import Loading from '../components/common/Loading.jsx';
import DetectionResults from '../components/face/DetectionResults.jsx';
import FaceBoundingBoxViewer from '../components/face/FaceBoundingBoxViewer.jsx';
import ImageUploader from '../components/face/ImageUploader.jsx';
import useApiAction from '../hooks/useApiAction.js';
import useObjectUrl from '../hooks/useObjectUrl.js';

export default function Detection() {
  const [file, setFile] = useState(null);
  const [analyzed, setAnalyzed] = useState(null);
  const [view, setView] = useState('original');
  const originalUrl = useObjectUrl(analyzed);
  const detect = useApiAction(detectFaces);
  const annotate = useApiAction(detectFacesAnnotated);
  const annotatedUrl = useObjectUrl(annotate.data);

  const change = (next) => {
    setFile(next);
    setAnalyzed(null);
    setView('original');
    detect.reset();
    annotate.reset();
  };

  const submit = async () => {
    if (!file) return;
    annotate.reset();
    setView('original');
    const result = await detect.run(file);
    if (result) setAnalyzed(file);
  };

  // Annotated JPEG is fetched lazily, only when the user asks for it.
  const showAnnotated = () => {
    setView('annotated');
    if (analyzed && !annotate.data && !annotate.loading) annotate.run(analyzed);
  };

  const tab = (id, text, onClick) => (
    <button
      type="button"
      role="tab"
      aria-selected={view === id}
      onClick={onClick}
      className={`rounded-md px-3 py-1 text-sm font-medium ${view === id ? 'bg-brand text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
    >
      {text}
    </button>
  );

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Upload Image">
        <div className="space-y-4">
          <ImageUploader file={file} onChange={change} disabled={detect.loading} label="Image" />
          <Button icon={ScanFace} loading={detect.loading} disabled={!file} onClick={submit}>Detect Faces</Button>
        </div>
      </Card>

      <Card
        title="Detection Results"
        actions={
          detect.data && (
            <div role="tablist" aria-label="Image view" className="flex gap-2">
              {tab('original', 'Original', () => setView('original'))}
              {tab('annotated', 'Annotated', showAnnotated)}
            </div>
          )
        }
      >
        {detect.loading && <Loading message="Detecting faces..." />}
        <ErrorMessage error={detect.error} />
        {detect.data && (
          <div className="space-y-4">
            {view === 'original' && originalUrl && (
              <FaceBoundingBoxViewer
                src={originalUrl}
                alt="Uploaded image with detected face boxes"
                faces={detect.data.faces.map((f) => ({ bbox: f.bbox }))}
              />
            )}
            {view === 'annotated' && (
              <>
                {annotate.loading && <Loading message="Rendering annotated image..." />}
                <ErrorMessage error={annotate.error} />
                {annotatedUrl && <img src={annotatedUrl} alt="Image annotated by the backend" className="max-h-[28rem] max-w-full rounded-md" />}
              </>
            )}
            <DetectionResults result={detect.data} />
          </div>
        )}
        {!detect.loading && !detect.error && !detect.data && (
          <EmptyState icon={ScanFace} title="No results yet" description="Upload an image and click Detect Faces." />
        )}
      </Card>
    </div>
  );
}
