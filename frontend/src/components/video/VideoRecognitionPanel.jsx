import { useState } from 'react';
import { Download, Film } from 'lucide-react';
import { recognizeVideo } from '../../api/recognition.js';
import useApiAction from '../../hooks/useApiAction.js';
import useObjectUrl from '../../hooks/useObjectUrl.js';
import Button from '../common/Button.jsx';
import Card from '../common/Card.jsx';
import EmptyState from '../common/EmptyState.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import Loading from '../common/Loading.jsx';
import ImageUploader from '../face/ImageUploader.jsx';

const ERROR_OVERRIDES = {
  413: 'Video exceeds the allowed upload size.',
  422: 'Video could not be processed.',
};

export default function VideoRecognitionPanel() {
  const [file, setFile] = useState(null);
  const { run, loading, error, data: blob, reset } = useApiAction(recognizeVideo, ERROR_OVERRIDES);
  const resultUrl = useObjectUrl(blob); // response is a binary mp4 Blob, never JSON

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Upload Video">
        <div className="space-y-4">
          <ImageUploader kind="video" file={file} onChange={(f) => { setFile(f); reset(); }} disabled={loading} />
          <Button icon={Film} loading={loading} disabled={!file} onClick={() => run(file)}>Process Video</Button>
        </div>
      </Card>

      <Card title="Processed Video">
        {loading && <Loading message="Processing video..." hint="Please wait." />}
        <ErrorMessage error={error} />
        {resultUrl && (
          <div className="space-y-3">
            <video src={resultUrl} controls className="w-full rounded-md bg-black" />
            <a
              href={resultUrl}
              download={`processed_${(file?.name ?? 'video').replace(/\.[^.]+$/, '')}.mp4`}
              className="inline-flex items-center gap-2 rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark"
            >
              <Download className="h-4 w-4" aria-hidden /> Download Processed Video
            </a>
          </div>
        )}
        {!loading && !error && !resultUrl && <EmptyState icon={Film} title="No processed video yet" />}
      </Card>
    </div>
  );
}
