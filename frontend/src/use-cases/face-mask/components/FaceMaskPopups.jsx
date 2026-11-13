import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, fmApiUrl } from '../api/index.js';
import { faceMaskEventLink } from '../../../layouts/routes.js';

/** Poll Face Mask directly so a missing Alert Service never delays a local safety popup. */
export default function FaceMaskPopups() {
  const [popups, setPopups] = useState([]);
  const [sound, setSound] = useState(false);
  const [cameras, setCameras] = useState({});
  const seen = useRef(new Set());
  const ready = useRef(false);
  const soundRef = useRef(false);

  useEffect(() => { soundRef.current = sound; }, [sound]);
  useEffect(() => {
    let active = true;
    const load = () => api.get('/cameras').then((items) => {
      if (active) setCameras(Object.fromEntries(items.map((camera) => [camera.id, camera.name])));
    }).catch(() => {});
    load();
    const timer = setInterval(load, 10000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const page = await api.get('/events?limit=20');
        if (!active) return;
        if (!ready.current) {
          page.items.forEach((event) => seen.current.add(event.id));
          ready.current = true;
          return;
        }
        const incoming = page.items.filter((event) => !seen.current.has(event.id));
        page.items.forEach((event) => seen.current.add(event.id));
        setPopups((previous) => {
          const updated = previous.map((popup) => page.items.find((event) => event.id === popup.id) || popup);
          return [...incoming.reverse(), ...updated].slice(0, 3);
        });
        if (incoming.length && soundRef.current) {
          try {
            const context = new AudioContext();
            const tone = context.createOscillator();
            tone.frequency.value = 700;
            tone.connect(context.destination);
            tone.start(); tone.stop(context.currentTime + 0.15);
            tone.onended = () => context.close();
          } catch { /* sound is optional and may be blocked until a click */ }
        }
      } catch { /* keep the shell usable while Face Mask is down */ }
    };
    poll();
    const timer = setInterval(poll, 1000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  return (
    <div aria-live="polite" style={{ position: 'fixed', right: 16, top: 80, zIndex: 100, width: 'min(360px, calc(100vw - 32px))' }}>
      {popups.map((event) => (
        <div key={event.id} role="alert" style={{ background: '#fff', border: '2px solid #dc2626', borderRadius: 8, boxShadow: '0 8px 28px #0004', marginBottom: 8, padding: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <strong>Masked person detected - Face Mask</strong>
            <button type="button" aria-label="Dismiss Face Mask alert" onClick={() => setPopups((items) => items.filter((item) => item.id !== event.id))}>×</button>
          </div>
          <div>{cameras[event.camera_id] || event.camera_id} · {event.covering_type || 'face covering'} · {new Date(event.first_seen).toLocaleTimeString()}</div>
          {event.snapshot_path && <img src={fmApiUrl(`/events/${event.id}/evidence/snapshot`)} alt="Face Mask event snapshot" style={{ width: 96, height: 64, objectFit: 'cover' }} />}
          <div>{event.clip_status === 'ready' ? 'Clip ready' : event.clip_status === 'failed' ? `Clip failed: ${event.clip_error}` : 'Recording clip…'}</div>
          <div style={{ display: 'flex', gap: 12 }}>
            <Link to={faceMaskEventLink(event.id)} onClick={() => setPopups((items) => items.filter((item) => item.id !== event.id))}>View</Link>
            <button type="button" aria-pressed={sound} onClick={() => setSound((value) => !value)}>Sound {sound ? 'on' : 'off'}</button>
          </div>
        </div>
      ))}
    </div>
  );
}
