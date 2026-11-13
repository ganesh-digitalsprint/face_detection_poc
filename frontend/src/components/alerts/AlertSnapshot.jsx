import { useEffect, useRef, useState } from 'react';
import { Camera } from 'lucide-react';
import { grillSnapshotRefs } from '../../api/alertServiceModel.js';
import { getGrillGateSnapshot } from '../../use-cases/grill-gate/api/grillGate.js';
import { fetchSourceThumbnail } from '../../api/sourceThumbnail.js';
import { loadSnapshot } from './snapshotResource.js';

export default function AlertSnapshot({ alert, large = false, evidenceIndex = 0, compact = false, thumbnailUrl }) {
  const ref = grillSnapshotRefs(alert)[evidenceIndex];
  const [retry, setRetry] = useState(0);
  const key = JSON.stringify([alert.sourceEventId || alert.id, ref?.retrieval_path, alert.evidenceStatus, retry]);
  const [image, setImage] = useState({ key: '', loading: false, url: '', error: '' });
  const dialog = useRef(null);
  const [sourceImage, setSourceImage] = useState({ key: '', url: '' });
  const [failedUrl,setFailedUrl]=useState('');
  const sourceKey=`${alert.useCase}:${alert.sourceEventId || alert.id}:${alert.primaryEvidenceId || ''}`;
  useEffect(() => {
    let active = true;
    if (!['vault_monitoring','branch_exterior','face_mask'].includes(alert.useCase) || thumbnailUrl) return undefined;
    fetchSourceThumbnail(alert,large ? 'full' : 'thumb').then((url)=>{if(active)setSourceImage({key:sourceKey,url});})
      .catch(()=>{if(active)setSourceImage({key:sourceKey,url:''});});
    return () => { active = false; };
  }, [sourceKey, thumbnailUrl, large, retry]);
  useEffect(() => {
    if (alert.useCase !== 'grill_gate' || !ref) return undefined;
    return loadSnapshot({ ref, fetchBlob: getGrillGateSnapshot, onChange: (next) => setImage({ ...next, key }) });
  }, [key]); // The key includes source, evidence, and capture state.
  const externalUrl=thumbnailUrl || (sourceImage.key===sourceKey ? sourceImage.url : '');
  const current = externalUrl && externalUrl!==failedUrl ? {url:externalUrl,loading:false,error:''}
    : externalUrl && externalUrl===failedUrl ? {url:'',loading:false,error:'Snapshot could not be displayed.'}
    : image.key === key ? image : { loading: alert.useCase === 'grill_gate' && Boolean(ref), url: '', error: '' };
  const imageFailed=()=>{if(externalUrl)setFailedUrl(externalUrl);else setImage((old)=>({...old,url:'',error:'Snapshot could not be displayed.'}));};
  const fallback = current.loading ? 'Loading snapshot\u2026' : current.error || (alert.evidenceStatus === 'PENDING' ? 'Snapshot capture pending' : alert.evidenceStatus === 'CAPTURED' ? 'Captured snapshot reference is missing.' : 'No captured snapshot is attached to this incident.');
  // The right-side card owns the single details button; no nested image button.
  if (compact) return <span className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-2xl bg-[#202530] text-[#B7BED0]">
    {current.url ? <img src={current.url} alt="Captured alert snapshot" className="h-full w-full object-cover" onError={imageFailed} />
      : <><Camera className="h-7 w-7" strokeWidth={1.7} aria-hidden="true" /><span className="sr-only">{fallback}</span></>}
  </span>;
  return <div className={`overflow-hidden rounded-xl ${large ? 'bg-[#18223c]' : 'bg-slate-100'}`}>
    {current.url ? <>
      <button type="button" onClick={() => dialog.current?.showModal()} className="block w-full" aria-label="Expand captured snapshot">
        <img src={current.url} onError={imageFailed} alt="Captured alert snapshot" className={`w-full ${large ? 'max-h-[440px] object-contain' : 'h-24 object-cover'}`} />
      </button>
      {large && <p className="px-3 py-2 text-xs text-white">Captured evidence{ref?.width && ref?.height ? ` - ${ref.width} x ${ref.height}` : ''} &middot; Select image to expand</p>}
      <dialog ref={dialog} className="m-auto max-h-[95vh] max-w-[95vw] rounded-xl bg-white p-3 backdrop:bg-black/70" onClick={(e) => { if (e.target === e.currentTarget) dialog.current.close(); }}>
        <button type="button" onClick={() => dialog.current.close()} className="mb-2 rounded border px-3 py-1">Close snapshot</button>
        <img src={current.url} alt="Expanded captured alert snapshot" className="max-h-[80vh] max-w-full object-contain" />
        <a download={`alert-${alert.sourceEventId || alert.id}.jpg`} href={current.url} className="mt-2 block text-sm text-indigo-700 underline">Download snapshot</a>
      </dialog>
    </> : <div role="status" className={`flex flex-col items-center justify-center gap-2 px-3 text-center text-xs ${large ? 'min-h-56 text-slate-200' : 'h-24 text-slate-500'}`}>{fallback}{current.error && <button type="button" onClick={() => (setFailedUrl(''), setRetry((n) => n + 1))} className="underline">Retry snapshot</button>}</div>}
  </div>;
}

