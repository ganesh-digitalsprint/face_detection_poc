import { getAlert, getEvidenceAccess } from '../use-cases/vault-monitoring/api/alerts.js';
import { api as branchApi } from '../use-cases/branch-exterior/api/index.js';
import { api as faceApi } from '../use-cases/face-mask/api/index.js';
import { BRANCH_BASE_URL, FACE_MASK_BASE_URL } from '../config/services.js';

export function sourceMediaUrl(base,path) {
  if(typeof path!=='string' || !path || path.includes('://') || path.includes('\\') || path.includes('?') || path.includes('#'))return '';
  const parts=path.replace(/^\/?storage\//,'').split('/');
  if(parts.some((part)=>!part || part==='.' || part==='..' || part.includes(':')))return '';
  return `${base}/storage/${parts.map(encodeURIComponent).join('/')}`;
}
export async function fetchSourceThumbnail(alert,variant='thumb') {
  if(alert.useCase==='vault_monitoring') {
    const id=alert.primaryEvidenceId || alert.evidenceRefs?.find((item)=>item.provider==='vault_monitoring')?.id;
    const evidenceId=id || (await getAlert(alert.sourceEventId)).primary_evidence_id;
    if(!evidenceId)return '';
    const response=await getEvidenceAccess([evidenceId],variant);
    return response.items?.find((item)=>item.id===evidenceId)?.url || '';
  }
  if(alert.useCase==='branch_exterior') {
    const row=await branchApi.get(`/events/${encodeURIComponent(alert.sourceEventId)}`);
    return sourceMediaUrl(BRANCH_BASE_URL,row.snapshot_path);
  }
  if(alert.useCase==='face_mask') {
    const row=await faceApi.get(`/events/${encodeURIComponent(alert.sourceEventId)}`);
    return sourceMediaUrl(FACE_MASK_BASE_URL,row.snapshot_path);
  }
  return '';
}
