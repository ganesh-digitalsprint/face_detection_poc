import { Square, Webcam } from 'lucide-react';
import { startWebcam } from '../../api/streams.js';
import useStreamSession from '../../hooks/useStreamSession.js';
import Button from '../common/Button.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import StreamViewer from './StreamViewer.jsx';

export default function WebcamPanel() {
  const { session, phase, error, begin, end } = useStreamSession(startWebcam);
  return (
    <div className="space-y-4">
      <StreamViewer key={session?.session_id ?? 'none'} session={session} status={phase === 'stopped' ? 'STOPPED' : undefined} />
      <ErrorMessage error={error} />
      {phase === 'stopping' && <p role="status" className="text-sm text-slate-500">Stopping stream...</p>}
      {phase === 'stopped' && <p role="status" className="text-sm text-slate-500">● Stream stopped</p>}
      <div className="flex gap-3">
        <Button icon={Webcam} loading={phase === 'starting'} disabled={!!session || phase === 'stopping'} onClick={() => begin()}>
          {phase === 'starting' ? 'Starting webcam...' : 'Start Webcam'}
        </Button>
        <Button variant="danger" icon={Square} loading={phase === 'stopping'} disabled={!session} onClick={end}>
          Stop Stream
        </Button>
      </div>
    </div>
  );
}
