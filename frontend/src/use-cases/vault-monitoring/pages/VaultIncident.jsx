import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Clock3, FileText } from 'lucide-react';
import { getIncident } from '../api/alerts.js';
import { describeError } from '../../../utils/errors.js';
import AlertCard from '../components/alerts/AlertCard.jsx';
import { normalizeAlert } from '../api/alerts.js';

export default function VaultIncident() {
  const { incidentId } = useParams();
  const [incident, setIncident] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    setLoading(true);
    getIncident(incidentId).then((data) => { if (live) { setIncident(data); setError(null); } })
      .catch((err) => { if (live) setError(describeError(err).message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [incidentId]);
  if (loading) return <div role="status" className="vault-card p-6">Loading incident…</div>;
  if (error) return <div role="alert" className="vault-card border-red-200 p-6 text-red-800">{error}<div><Link to="/alerts/vault" className="mt-3 inline-flex min-h-10 items-center gap-2 text-sm font-semibold underline"><ArrowLeft className="h-4 w-4"/>Back to alerts</Link></div></div>;
  if (!incident) return null;
  const alerts = (incident.alerts || []).map((item) => normalizeAlert({ ...item, alert_type: item.alert_type, allowed_actions: item.allowed_actions || [] }));
  return <div className="mx-auto max-w-5xl space-y-5">
    <Link to="/alerts/vault" className="inline-flex min-h-10 items-center gap-2 text-sm font-semibold text-[#34479B]"><ArrowLeft className="h-4 w-4" aria-hidden/>Back to alerts</Link>
    <header className="vault-card p-5 sm:p-7"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Incident {incident.incident_number}</p><h1 className="mt-1 text-2xl font-bold text-[#152449]">{incident.title}</h1><p className="mt-2 text-sm text-slate-600">{incident.description || 'No incident description.'}</p></div><div className="flex gap-2"><span className="rounded-full bg-red-50 px-3 py-1 text-xs font-bold text-red-800">{incident.severity}</span><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-700">{incident.status}</span></div></div>
      <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-slate-100 pt-4 text-sm sm:grid-cols-4"><div><dt className="text-xs text-slate-500">Camera</dt><dd className="mt-1 font-semibold">{incident.camera_id || '—'}</dd></div><div><dt className="text-xs text-slate-500">Session</dt><dd className="mt-1 break-all font-semibold">{incident.session_ref || '—'}</dd></div><div><dt className="text-xs text-slate-500">Opened</dt><dd className="mt-1 font-semibold">{incident.opened_at ? new Date(incident.opened_at).toLocaleString([], { timeZoneName: 'short' }) : '—'}</dd></div><div><dt className="text-xs text-slate-500">Legal hold</dt><dd className="mt-1 font-semibold">{incident.legal_hold ? 'On' : 'Off'}</dd></div></dl>
    </header>
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <section className="space-y-3"><h2 className="text-lg font-bold text-[#152449]">Related alerts</h2>{alerts.length ? alerts.map((alert) => <AlertCard key={alert.id} alert={alert} variant="row"/>) : <p className="vault-card p-5 text-sm text-slate-600">No linked alerts.</p>}</section>
      <aside className="space-y-5"><section className="vault-card p-5"><h2 className="flex items-center gap-2 font-bold text-[#152449]"><FileText className="h-4 w-4"/>Evidence</h2>{incident.evidence?.length ? <ul className="mt-3 space-y-2">{incident.evidence.map((item) => <li key={item.id} className="rounded-lg border border-slate-100 p-3 text-xs">{item.evidence_type} · {item.mime_type || 'image'} · {item.available ? 'Available' : 'Removed'}</li>)}</ul> : <p className="mt-3 text-sm text-slate-500">No evidence attached.</p>}</section>
        <section className="vault-card p-5"><h2 className="flex items-center gap-2 font-bold text-[#152449]"><Clock3 className="h-4 w-4"/>Timeline</h2>{incident.timeline?.length ? <ol className="mt-3 space-y-3">{incident.timeline.map((item, index) => <li key={`${item.ref}-${index}`} className="border-l-2 border-slate-200 pl-3"><p className="text-xs font-semibold text-[#152449]">{item.summary}</p><p className="mt-1 text-xs text-slate-500">{new Date(item.at).toLocaleString([], { timeZoneName: 'short' })}{item.actor_label ? ` · ${item.actor_label}` : ''}</p></li>)}</ol> : <p className="mt-3 text-sm text-slate-500">No timeline events.</p>}</section>
      </aside>
    </div>
  </div>;
}
