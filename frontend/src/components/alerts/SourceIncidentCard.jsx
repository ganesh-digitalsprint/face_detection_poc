import CompactAlertCard from './CompactAlertCard.jsx';
import { sourceIncidentView } from './sourceIncidentModel.js';
const branchCategories = {
  weapon: 'Weapon-like object', fighting: 'Possible fight', violent_action: 'Possible violent action',
  zone_tamper: 'Possible zone tampering', gate_tampering: 'Possible gate tampering',
  snatch_flee: 'Possible snatch and flight', climbing: 'Possible climbing',
  drop_from_height: 'Possible jump or drop', zone_watching: 'Possible surveillance',
  zone_group: 'Suspicious gathering', atm_group: 'ATM gathering', group: 'Suspicious gathering',
  running: 'Running', jumping: 'Jumping', fallen: 'Person down',
  movement: 'Unusual movement', gathering: 'Gathering', intrusion: 'Zone intrusion',
};
export function branchIncidentCategory(event) {
  const kind = event?.meta?.kind || event?.scenario;
  return branchCategories[kind] || (kind ? String(kind).replaceAll('_', ' ') : 'Suspicious activity');
}
export default function SourceIncidentCard({event,useCase,common,thumbnailUrl,onSelect}) {
  const baseAlert=sourceIncidentView(event,useCase,common);
  const rawSeverity=String(event.severity || '').toUpperCase();
  const alert=useCase==='branch_exterior' && ['CRITICAL','HIGH','MEDIUM','LOW','INFO'].includes(rawSeverity)
    ? { ...baseAlert, severity:rawSeverity } : baseAlert;
  return <CompactAlertCard alert={alert} thumbnailUrl={thumbnailUrl} onSelect={()=>onSelect(event.id)}
    categoryLabel={useCase === 'branch_exterior' ? branchIncidentCategory(event) : ''}>
    <p className="px-4 pb-2 pt-1 text-xs text-slate-500">{event.camera_name || alert.title} - Incident: {alert.status}{event.status ? ` - Review: ${event.status}` : ''}</p>
  </CompactAlertCard>;
}
