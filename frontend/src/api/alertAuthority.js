import { getAlert, updateAlert } from '../use-cases/vault-monitoring/api/alerts.js';
import { getGrillGateSourceAlert, getGrillGateAlert, getGrillGateVideoResults, getLiveActiveAlerts, getLiveAlertHistory, acknowledgeGrillGateAlert, resolveGrillGateAlert, dismissGrillGateAlert } from '../use-cases/grill-gate/api/grillGate.js';
import { loadGrillSourceAlert } from './grillAlertLookup.js';
import { availableActions } from './alertServiceModel.js';
import { transitionServiceAlert } from './alertService.js';

const sourceOwned = (alert) => ['grill_gate','vault_monitoring'].includes(alert.useCase);
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
      const row=await (alert.useCase==='grill_gate' ? loadGrillSourceAlert(api,alert,signal) : api.vaultGet(alert.sourceEventId,signal));
      return sourceView(alert,row);
    },
    transition:async(alert,target,body)=> {
      if (!availableActions(alert,true).some((action)=>action.target===target)) throw new Error('This action is not allowed by the source alert.');
      if (!sourceOwned(alert)) return api.common(alert.id,target,body);
      if (!(alert.sourceAllowedActions || []).includes(target)) throw new Error('This action is not allowed by the source alert.');
      if (!alert.sourceApiId || !alert.sourceRowVersion) throw new Error('Load the latest source alert before changing its status.');
      let row;
      if (alert.useCase==='vault_monitoring') row=await api.vaultAct(alert.sourceApiId,{ACKNOWLEDGED:'acknowledge',RESOLVED:'resolve',DISMISSED:'dismiss'}[target],{...body,expected_version:alert.sourceRowVersion});
      else row=await api.grillAct(alert.sourceApiId,target,alert.sourceRowVersion,body.note);
      return sourceView(alert,row);
    },
  };
}
export const alertAuthority=createAlertAuthority({
  grillGet:getGrillGateSourceAlert,grillById:getGrillGateAlert,grillVideo:getGrillGateVideoResults,grillActive:getLiveActiveAlerts,grillHistory:getLiveAlertHistory,vaultGet:getAlert,vaultAct:updateAlert,common:transitionServiceAlert,
  grillAct:(id,target,version,note)=> target==='ACKNOWLEDGED' ? acknowledgeGrillGateAlert(id,version,note) : target==='RESOLVED' ? resolveGrillGateAlert(id,version,note) : dismissGrillGateAlert(id,version,note),
});

export function authorityErrorMessage(error) {
  const status=error?.response?.status;
  if(status===401 || status===403)return 'The source backend rejected operator access. Check the configured Vault operator key and permissions.';
  if(status===404)return 'The source alert could not be found. Check that the source backend and Common Alerts use the same persisted data.';
  return `Could not load the latest source alert${status ? ` (HTTP ${status})` : ''}. Retry before taking an action.`;
}
