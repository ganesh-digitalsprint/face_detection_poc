import { FileVideo } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

export default function VaultRoomReplayPreview({ replay, zonesLayout = false }) {
  const [previewError, setPreviewError] = useState(false);
  const localVideo = useRef(null);
  const showProcessed = Boolean(!replay.previewingFile && (replay.frameUrl || replay.session?.frame_sequence > 0) && !zonesLayout);
  useEffect(() => { if (showProcessed) localVideo.current?.pause(); }, [showProcessed]);
  useEffect(() => setPreviewError(false), [replay.localUrl]);
  const status = replay.busy && !replay.session ? `Uploading ${replay.uploadProgress}%` : replay.session?.status || (replay.file ? 'Ready to process' : 'Choose a video');
  const elapsed = replay.session?.current_time || 0;
  return <div className="room-camera-frame room-replay-frame relative flex items-center justify-center overflow-hidden">
    {showProcessed && (replay.frameUrl ? <img src={replay.frameUrl} alt="Processed Vault Room replay with person tracking" className="absolute inset-0 h-full w-full object-contain" /> : <p role="status" className="text-sm text-slate-300">Loading processed preview…</p>)}
    {replay.localUrl && <video ref={localVideo} hidden={showProcessed} key={replay.localUrl} src={replay.localUrl} controls={!zonesLayout} playsInline preload="metadata"
        onLoadedMetadata={(event) => replay.setDuration(event.currentTarget.duration)}
        onError={() => { replay.setDuration(null); setPreviewError(true); }}
        className="absolute inset-0 h-full w-full object-contain" />}
    {!replay.localUrl && !showProcessed && <div className="flex flex-col items-center gap-3 text-slate-400"><FileVideo className="h-9 w-9" aria-hidden /><p className="text-sm">{replay.session?.status === 'unavailable' ? 'Saved replay activity history' : replay.session?.status === 'restoring' ? 'Restoring replay…' : 'Choose a video to preview'}</p></div>}
    {!zonesLayout && <span className="pointer-events-none absolute left-3 top-3 rounded-full bg-black/70 px-3 py-1.5 text-xs font-bold text-white">Replay test · {status}</span>}
    {!zonesLayout && !replay.previewingFile && !replay.showPoseDebug && replay.session?.metadata && <span className="pointer-events-none absolute right-3 top-3 rounded-full bg-black/70 px-3 py-1.5 text-xs font-bold text-white">{elapsed.toFixed(1)}s / {replay.session.metadata.duration.toFixed(1)}s</span>}
    {previewError && !showProcessed && <p role="status" className="absolute inset-x-3 bottom-16 rounded-lg bg-black/80 p-3 text-center text-sm text-white">{zonesLayout ? 'Your browser cannot preview this codec. Choose a browser-compatible MP4 or WebM video to select frames.' : 'Your browser cannot preview this codec. Select Process video to view decoded frames.'}</p>}
  </div>;
}
