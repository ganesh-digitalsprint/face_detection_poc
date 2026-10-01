import { useState } from 'react';
import { VideoOff } from 'lucide-react';
import { resolveStreamUrl } from '../../api/streams.js';
import EmptyState from '../common/EmptyState.jsx';
import StatusBadge from '../common/StatusBadge.jsx';

/** MJPEG (multipart/x-mixed-replace) is rendered natively by <img>; never parsed as JSON. */
export default function StreamViewer({ session, status }) {
  const [failed, setFailed] = useState(false);
  if (!session) {
    return <EmptyState icon={VideoOff} title={status === 'STOPPED' ? 'Stream stopped' : 'No active stream'} />;
  }
  return (
    <div className="space-y-3">
      <div className="flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-slate-900">
        {failed ? (
          <p className="px-4 text-center text-sm text-red-300">Stream failed to load. Stop and start again.</p>
        ) : (
          <img
            key={session.session_id}
            src={resolveStreamUrl(session)}
            alt="Live annotated camera stream"
            className="h-full w-full object-contain"
            onError={() => setFailed(true)}
          />
        )}
      </div>
      <div className="flex items-center gap-3 text-sm">
        <StatusBadge status={failed ? 'ERROR' : 'LIVE'} />
        <span className="text-slate-500">Session: <code>{session.session_id}</code></span>
      </div>
    </div>
  );
}
