import { getAlert, getEvidenceAccess } from '../use-cases/vault-monitoring/api/alerts.js';
import { getGrillGateSourceAlert, getGrillGateSnapshot } from '../use-cases/grill-gate/api/grillGate.js';
import { api as branchApi } from '../use-cases/branch-exterior/api/index.js';
import { api as faceApi } from '../use-cases/face-mask/api/index.js';
import { BRANCH_BASE_URL, FACE_MASK_BASE_URL } from '../config/services.js';
import { sourceMediaUrl } from './sourceThumbnail.js';
import { grillSnapshotRefs } from './alertServiceModel.js';

export function probeImage(url, signal) {
  return new Promise((resolve) => {
    const image = new Image();
    const finish = (ok) => { clearTimeout(timer); signal?.removeEventListener('abort', abort); image.onload=null; image.onerror=null; resolve(ok); };
    const abort = () => { finish(false); image.src=''; };
    const timer = setTimeout(abort, 8000);
    image.onload = () => finish(image.naturalWidth > 0);
    image.onerror = () => finish(false);
    signal?.addEventListener('abort', abort, { once:true });
    if(signal?.aborted) abort(); else image.src=url;
  });
}

async function probeClip(url, signal) {
  const ctl=new AbortController();
  const abort=()=>ctl.abort();
  signal?.addEventListener('abort',abort,{once:true});
  const timer=setTimeout(abort,8000);
  try {
    if(signal?.aborted) return false;
    const response=await fetch(url,{headers:{Range:'bytes=0-0'},signal:ctl.signal});
    const ok=response.ok && (response.headers.get('content-type') || '').startsWith('video/');
    await response.body?.cancel();
    return ok;
  } catch { return false; }
  finally {clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}

// Temporary in-memory preview only; no file is copied or persisted.
const blobPreview=(blob)=>new Promise((resolve,reject)=>{
  const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Snapshot unavailable'));reader.readAsDataURL(blob);
});

export function evidenceFields(value) {
  return Object.fromEntries(['evidenceManaged','evidenceChecked','evidenceStatus','evidenceCount','snapshotCount','clipCount',
    'evidenceRefs','evidenceSnapshots','thumbnailUrl','evidencePending','evidenceUnavailableReason','onEvidenceError'].map((key)=>[key,value[key]]));
}

export function verifiedEvidence(refs=[], snapshots=[], pending=false, status=null, reason=null) {
  return {evidenceManaged:true,evidenceChecked:true,evidenceRefs:refs,evidenceSnapshots:snapshots,
    evidenceCount:refs.length,snapshotCount:snapshots.length,clipCount:refs.filter((ref)=>ref.type==='clip').length,
    evidenceStatus:refs.length ? 'CAPTURED' : status || (pending ? 'PENDING' : 'UNAVAILABLE'),
    evidenceUnavailableReason:refs.length ? null : reason,
    evidencePending:pending,thumbnailUrl:snapshots[0]?.url || ''};
}

export function removeUnavailableSnapshot(current,url) {
  const removed=current.evidenceSnapshots.filter((item)=>item.url===url).map((item)=>item.ref.id);
  if(!removed.length)return current;
  return verifiedEvidence(current.evidenceRefs.filter((ref)=>!removed.includes(ref.id)),
    current.evidenceSnapshots.filter((item)=>item.url!==url),current.evidencePending,
    'FAILED','evidence_retrieval_failed');
}

const defaults={vault:getAlert,vaultAccess:getEvidenceAccess,gate:getGrillGateSourceAlert,gateSnapshot:getGrillGateSnapshot,
  branch:(id)=>branchApi.get(`/events/${encodeURIComponent(id)}`),
  face:(id)=>faceApi.get(`/events/${encodeURIComponent(id)}/evidence`),probeImage,probeClip,blobPreview};

export function createEvidenceResolver(api=defaults) {
  return async(alert,signal)=>{
    let candidates=[], pending=false, sourceStatus=null, unavailableReason=null;
    try {
      if(alert.useCase==='vault_monitoring') {
        const row=await api.vault(alert.sourceEventId,signal);
        let refs=row.evidence_refs || alert.evidenceRefs?.filter((ref)=>ref.provider==='vault_monitoring') || [];
        if(row.evidence_count===0) refs=[];
        else if(row.primary_evidence_id && !refs.some((ref)=>ref.id===row.primary_evidence_id)) refs=[...refs,{provider:'vault_monitoring',id:row.primary_evidence_id,type:'snapshot'}];
        refs=[...new Map(refs.map((ref)=>[ref.id,{...ref,type:'snapshot'}])).values()].slice(0,50);
        pending=row.evidence_status==='PENDING';
        if(refs.length) {
          const response=await api.vaultAccess(refs.map((ref)=>ref.id),'thumb');
          candidates=refs.map((ref)=>({ref,url:response.items?.find((item)=>item.id===ref.id)?.url})).filter((item)=>item.url);
        }
      } else if(alert.useCase==='grill_gate') {
        let row;
        try {row=await api.gate(alert.sourceEventId,signal);} catch(error) {if(error?.response?.status!==404)throw error;}
        if(row && row.source_event_id!==alert.sourceEventId)throw new Error('Mismatched evidence source');
        const source=row ? {...alert,evidenceRefs:row.evidence_refs || []} : alert;
        pending=(row?.evidence_status || row?.domain_data?.evidence_status || alert.evidenceStatus)==='PENDING';
        for(const ref of grillSnapshotRefs(source)) {
          try {
            const blob=await api.gateSnapshot(ref,signal);
            if(blob?.type?.startsWith('image/')) candidates.push({ref:{...ref,type:'snapshot'},url:await api.blobPreview(blob)});
          } catch { /* An expired or deleted snapshot is unavailable, not a page failure. */ }
        }
      } else if(alert.useCase==='branch_exterior') {
        const row=await api.branch(alert.sourceEventId,signal);
        if(['PENDING','FAILED','UNAVAILABLE'].includes(alert.evidenceStatus)) sourceStatus=alert.evidenceStatus;
        unavailableReason=alert.evidenceUnavailableReason || null;
        const evidenceState=String(row.meta?.evidence || '');
        if(evidenceState==='pending' || evidenceState.startsWith('pending:')) pending=true;
        else if(evidenceState.startsWith('failed:')) {
          sourceStatus='FAILED'; unavailableReason=evidenceState.slice('failed:'.length) || 'evidence_capture_failed';
        } else if(evidenceState.startsWith('not_saved:')) {
          sourceStatus='UNAVAILABLE'; unavailableReason=evidenceState.slice('not_saved:'.length) || 'not_captured';
        }
        for(const [type,path] of [['snapshot',row.snapshot_path],['clip',row.clip_path]]) {
          const url=sourceMediaUrl(BRANCH_BASE_URL,path,'branch_exterior');
          if(url)candidates.push({ref:{provider:'branch_exterior',id:`${alert.sourceEventId}:${type}`,type,event_path:`/api/events/${encodeURIComponent(alert.sourceEventId)}`},url});
        }
        if((row.snapshot_path || row.clip_path) && !candidates.length) {
          sourceStatus='FAILED'; unavailableReason='invalid_evidence_path';
        }
      } else if(alert.useCase==='face_mask') {
        const row=await api.face(alert.sourceEventId,signal);
        pending=row.clip_status==='pending';
        for(const [type,path] of [['snapshot',row.snapshot_url],['clip',row.clip_url]]) {
          const expected=`/api/events/${encodeURIComponent(alert.sourceEventId)}/evidence/${type}`;
          if(path===expected)candidates.push({ref:{provider:'face_mask',id:`${alert.sourceEventId}:${type}`,type,retrieval_path:path},url:`${FACE_MASK_BASE_URL}${path}`});
        }
      }
      const accessible=[];
      for(const item of candidates) {
        if(signal?.aborted)throw new DOMException('Aborted','AbortError');
        if(await (item.ref.type==='clip' ? api.probeClip(item.url,signal) : api.probeImage(item.url,signal))) accessible.push(item);
      }
      if(!accessible.length && candidates.length) {
        sourceStatus=alert.useCase==='branch_exterior' ? 'FAILED' : 'UNAVAILABLE';
        unavailableReason=alert.useCase==='branch_exterior' ? 'evidence_retrieval_failed' : null;
      }
      return verifiedEvidence(accessible.map((item)=>({...item.ref,url:item.url})),accessible.filter((item)=>item.ref.type==='snapshot'),pending,sourceStatus,unavailableReason);
    } catch(error) {
      if(signal?.aborted)throw error;
      return verifiedEvidence([],[],false,alert.useCase==='branch_exterior'?'FAILED':'UNAVAILABLE',
        alert.useCase==='branch_exterior'?'evidence_retrieval_failed':null);
    }
  };
}
export const resolveAlertEvidence=createEvidenceResolver();

export function matchesEvidence(alert,filter) {
  if(!filter)return true;
  if(filter==='CAPTURED')return (alert.snapshotCount || 0)>0;
  return alert.evidenceStatus===filter;
}
