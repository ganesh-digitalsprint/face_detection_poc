import CompactAlertCard from './CompactAlertCard.jsx';
import { sourceIncidentView } from './sourceIncidentModel.js';
export default function SourceIncidentCard({event,useCase,common,thumbnailUrl,onSelect}) {
  const alert=sourceIncidentView(event,useCase,common);
  return <CompactAlertCard alert={alert} thumbnailUrl={thumbnailUrl} onSelect={()=>onSelect(event.id)}>
    <p className="px-4 pb-2 pt-1 text-xs text-slate-500">{event.camera_name || alert.title} - Incident: {alert.status}{event.status ? ` - Review: ${event.status}` : ''}</p>
  </CompactAlertCard>;
}
