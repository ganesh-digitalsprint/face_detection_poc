import { getAlert, updateAlert } from '../use-cases/vault-monitoring/api/alerts.js';
import { getGrillGateSourceAlert, getGrillGateAlert, getGrillGateVideoResults, getLiveActiveAlerts, getLiveAlertHistory, acknowledgeGrillGateAlert, resolveGrillGateAlert, dismissGrillGateAlert } from '../use-cases/grill-gate/api/grillGate.js';
import { loadGrillSourceAlert } from './grillAlertLookup.js';
import { availableActions } from './alertServiceModel.js';
import { transitionServiceAlert } from './alertService.js';
import { api as faceApi } from '../use-cases/face-mask/api/index.js';

const sourceOwned = (alert) => ['grill_gate','vault_monitoring','face_mask'].includes(alert.useCase);
const faceStatus = {OPEN:'OPEN',UNDER_REVIEW:'ACKNOWLEDGED',CONFIRMED:'ACKNOWLEDGED',FALSE_POSITIVE:'DISMISSED',CLOSED:'RESOLVED'};
const faceActions = {OPEN:['ACKNOWLEDGED','RESOLVED','DISMISSED'],UNDER_REVIEW:['RESOLVED','DISMISSED'],CONFIRMED:['RESOLVED'],FALSE_POSITIVE:[],CLOSED:[]};
const faceView = (alert,row) => {
  if (!row?.id || row.id !== alert.sourceEventId || !faceStatus[row.status] || !Number.isInteger(row.review_version))
    throw new Error('The Face Mask source returned an invalid or mismatched event. Actions are unavailable.');
  return {...alert,status:faceStatus[row.status],sourceStatus:row.status,sourceApiId:row.id,
    sourceRowVersion:row.review_version,sourceAllowedActions:faceActions[row.status],confirmedSourceVersion:row.review_version,
    cameraName:row.camera_name || alert.cameraName,branchName:row.branch_name || alert.branchName,
    branchCode:row.branch_code || alert.branchCode,placeName:row.place_name || alert.placeName,
    regionName:row.region_name || alert.regionName,branchManager:row.branch_manager || alert.branchManager,
    domainData:{...alert.domainData,confidence:row.score,covering_type:row.covering_type,track_id:row.track_id}};
};
const sourceView = (alert, row) => {
  if (!row?.id || !Number.isInteger(row.row_version) || row.row_version < 1 || !['OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED'].includes(row.status) ||
    (alert.useCase === 'grill_gate' ? row.source_event_id !== alert.sourceEventId : row.id !== alert.sourceEventId)) {
    throw new Error('The source returned an invalid or mismatched alert. Actions are unavailable.');
  }
  return ({ ...alert, status:row.status, sourceStatus:row.status,
  sourceApiId:row.id, sourceRowVersion:row.row_version, resolutionNote:row.resolution_note || alert.resolutionNote,
  confirmedSourceVersion:row.source_event_version || row.row_version,
  sourceAllowedActions:(row.allowed_actions || []).map((s)=>({acknowledge:'ACKNOWLEDGED',resolve:'RESOLVED',dismiss:'DISMISSED'}[s] || s)),
  evidenceRefs:row.evidence_refs || alert.evidenceRefs, primaryEvidenceId:row.primary_evidence_id,
  evidenceStatus:row.evidence_status || alert.evidenceStatus,
  title:row.title || alert.title, summary:row.summary || row.message || alert.summary,
  acknowledgementComment:row.acknowledgement_comment ?? alert.acknowledgementComment,
  acknowledgedAt:row.acknowledged_at ?? alert.acknowledgedAt, acknowledgedBy:row.acknowledged_by ?? alert.acknowledgedBy,
  dismissedAt:row.dismissed_at ?? alert.dismissedAt, dismissedBy:row.dismissed_by ?? alert.dismissedBy,
  resolvedBy:row.resolved_by ?? alert.resolvedBy,
  resolvedAt:row.resolved_at ?? alert.resolvedAt });
};

export function createAlertAuthority(api) {
  return {
    load:async(alert,signal)=> {
      if (!sourceOwned(alert)) return alert;
      if (!alert.sourceEventId) throw new Error('Missing source-event identity. Actions are unavailable.');
      if(alert.useCase==='face_mask') return faceView(alert,await api.faceGet(alert.sourceEventId,signal));
      const row=await (alert.useCase==='grill_gate' ? loadGrillSourceAlert(api,alert,signal) : api.vaultGet(alert.sourceEventId,signal));
      return sourceView(alert,row);
    },
    transition:async(alert,target,body)=> {
      if (!availableActions(alert,true).some((action)=>action.target===target)) throw new Error('This action is not allowed by the source alert.');
      if (!sourceOwned(alert)) return api.common(alert.id,target,body);
      if (!(alert.sourceAllowedActions || []).includes(target)) throw new Error('This action is not allowed by the source alert.');
      if (!alert.sourceApiId || !alert.sourceRowVersion) throw new Error('Load the latest source alert before changing its status.');
      let row;
      if(alert.useCase==='face_mask') {
        const act=async(to,current)=>api.faceReview(current.id,to,body.note || '',current.review_version);
        let current=await api.faceGet(alert.sourceEventId);
        if(current.review_version!==alert.sourceRowVersion) throw new Error('This Face Mask event changed since it was loaded. Reload it and retry.');
        if(target==='ACKNOWLEDGED') current=await act('UNDER_REVIEW',current);
        else if(target==='DISMISSED') {
          if(current.status==='OPEN') current=await act('UNDER_REVIEW',current);
          current=await act('FALSE_POSITIVE',current);
        } else if(target==='RESOLVED') {
          if(current.status==='OPEN') current=await act('UNDER_REVIEW',current);
          if(current.status==='UNDER_REVIEW') current=await act('CONFIRMED',current);
          current=await api.faceClose(current.id,body.note || '',current.review_version);
        }
        return faceView(alert,current);
      }
      if (alert.useCase==='vault_monitoring') row=await api.vaultAct(alert.sourceApiId,{ACKNOWLEDGED:'acknowledge',RESOLVED:'resolve',DISMISSED:'dismiss'}[target],{...body,expected_version:alert.sourceRowVersion});
      else row=await api.grillAct(alert.sourceApiId,target,alert.sourceRowVersion,body.note);
      return sourceView(alert,row);
    },
  };
}
export const alertAuthority=createAlertAuthority({
  grillGet:getGrillGateSourceAlert,grillById:getGrillGateAlert,grillVideo:getGrillGateVideoResults,grillActive:getLiveActiveAlerts,grillHistory:getLiveAlertHistory,vaultGet:getAlert,vaultAct:updateAlert,common:transitionServiceAlert,
  grillAct:(id,target,version,note)=> target==='ACKNOWLEDGED' ? acknowledgeGrillGateAlert(id,version,note) : target==='RESOLVED' ? resolveGrillGateAlert(id,version,note) : dismissGrillGateAlert(id,version,note),
  faceGet:(id)=>faceApi.get(`/events/${encodeURIComponent(id)}`),
  faceReview:(id,to,remarks,expected_version)=>faceApi.post(`/events/${encodeURIComponent(id)}/review`,{to_status:to,remarks,reviewer:'common-alerts-operator',expected_version}),
  faceClose:(id,remarks,expected_version)=>faceApi.post(`/events/${encodeURIComponent(id)}/close`,{remarks,reviewer:'common-alerts-operator',expected_version}),
});

export function authorityErrorMessage(error) {
  const status=error?.response?.status;
  if(status===401 || status===403)return 'The source backend rejected operator access. Check the configured Vault operator key and permissions.';
  if(status===404)return 'The source alert could not be found. Check that the source backend and Common Alerts use the same persisted data.';
  return `Could not load the latest source alert${status ? ` (HTTP ${status})` : ''}. Retry before taking an action.`;
}
