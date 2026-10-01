import { useState } from 'react';
import { CircleStop, Cctv } from 'lucide-react';
import { startCCTV } from '../../api/streams.js';
import useStreamSession from '../../hooks/useStreamSession.js';
import Button from '../common/Button.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import StreamViewer from './StreamViewer.jsx';

// The backend exposes no endpoint listing configured cameras (RTSP_URLS stays server-side),
// so the user picks a numeric stream_index. Only the index is ever sent; no RTSP URL/credentials.
const MAX_CAMERAS = 8;

export default function CCTVPanel() {
  const [index, setIndex] = useState(0);
  const { session, phase, error, begin, end } = useStreamSession(startCCTV);
  return (
    <div className="space-y-4">
      <div className="max-w-xs">
        <label htmlFor="cctv_index" className="mb-1 block text-sm font-medium text-slate-700">Camera</label>
        <select
          id="cctv_index"
          value={index}
          disabled={!!session || phase === 'starting'}
          onChange={(e) => setIndex(Number(e.target.value))}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          {Array.from({ length: MAX_CAMERAS }, (_, i) => (
            <option key={i} value={i}>Camera {i + 1} (stream_index {i})</option>
          ))}
        </select>
      </div>
      <StreamViewer key={session?.session_id ?? 'none'} session={session} status={phase === 'stopped' ? 'STOPPED' : undefined} />
      <ErrorMessage error={error} />
      {phase === 'stopping' && <p role="status" className="text-sm text-slate-500">Stopping stream...</p>}
      {phase === 'stopped' && <p role="status" className="text-sm text-slate-500">● Stream stopped</p>}
      <div className="flex gap-3">
        <Button icon={Cctv} loading={phase === 'starting'} disabled={!!session || phase === 'stopping'} onClick={() => begin(index)}>
          {phase === 'starting' ? 'Starting CCTV...' : 'Start CCTV'}
        </Button>
        <Button variant="danger" icon={CircleStop} loading={phase === 'stopping'} disabled={!session} onClick={end}>
          Stop Stream
        </Button>
      </div>
    </div>
  );
}
