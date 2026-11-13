export function sourceIncidentView(event,useCase,common) {
  return common || { id:event.id,useCase,sourceEventId:event.id,sourceEventType:event.scenario || 'FACE_CONCEALMENT',
    title:event.camera_name || 'Concealment detected',summary:event.message || `Track #${event.track_id} - score ${Number(event.score || 0).toFixed(2)} - ${event.frame_count || 0} frames`,
    severity:useCase==='face_mask'?'HIGH':({critical:'CRITICAL',high:'HIGH',medium:'WARNING',low:'WARNING',info:'INFO'}[event.severity] || 'INFO'),
    status:({open:'OPEN',under_review:'ACKNOWLEDGED',confirmed:'ACKNOWLEDGED',closed:'RESOLVED',false_positive:'DISMISSED',OPEN:'OPEN',UNDER_REVIEW:'ACKNOWLEDGED',CONFIRMED:'ACKNOWLEDGED',CLOSED:'RESOLVED',FALSE_POSITIVE:'DISMISSED'}[event.status] || 'OPEN'),
    occurredAt:event.created_at || event.first_seen,evidenceRefs:[] };
}
