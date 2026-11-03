import { useEffect, useState } from 'react';
import { api } from '../api/index.js';
import Modal from '../../branch-exterior/components/Modal.jsx';

/**
 * Register an RTSP/HTTP camera, a webcam, an uploaded video or a video already on the server.
 * Same form pattern as Branch Exterior. The password is sent once and never shown again by the API.
 */
export default function AddCameraModal({ onClose, onCreated }) {
  const [form, setForm] = useState({ name: '', type: 'rtsp', location: '', source: '', user: '', pass: '' });
  const [file, setFile] = useState(null);
  const [browse, setBrowse] = useState({ state: 'idle', files: [] });
  const [picked, setPicked] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  useEffect(() => { setForm((f) => ({ ...f, source: f.type === 'webcam' ? '0' : '' })); }, [form.type]);

  useEffect(() => {
    if (form.type !== 'folder') return undefined;
    let stale = false;
    setBrowse({ state: 'loading', files: [] });
    api.get('/uploads/browse')
      .then((files) => { if (!stale) setBrowse({ state: 'ok', files }); })
      .catch(() => { if (!stale) setBrowse({ state: 'error', files: [] }); });
    return () => { stale = true; };
  }, [form.type]);

  const submit = async () => {
    setError('');
    if (!form.name.trim()) { setError('Please give the camera a name.'); return; }
    setBusy(true);
    try {
      let source = form.source.trim();
      if (form.type === 'rtsp' && !source) throw new Error('Please enter the RTSP/HTTP URL.');
      if (form.type === 'upload') {
        if (!file) throw new Error('Please choose a video file.');
        const fd = new FormData(); fd.append('file', file);
        source = (await api.postForm('/uploads/video', fd)).path;
      }
      if (form.type === 'folder') {
        if (!picked) throw new Error('Please pick a video from the list.');
        source = picked;
      }
      const created = await api.post('/cameras', {
        name: form.name.trim(), cam_type: form.type, source, username: form.user.trim(), password: form.pass,
        location: form.location.trim(), enabled: true, loop_video: false,
      });
      onClose();
      if (onCreated) await onCreated(created);
    } catch (e) {
      setError(e.message);
    } finally { setBusy(false); }
  };

  return (
    <Modal
      title="Add a camera"
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="bx-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="bx-btn bx-btn-primary" disabled={busy} onClick={submit}>{busy ? 'Adding…' : 'Add camera'}</button>
        </>
      )}
    >
      {error && <div className="bx-diag" role="alert">{error}</div>}
      <label className="bx-field">Camera name
        <input className="bx-input" value={form.name} onChange={set('name')} placeholder="e.g. Main entrance" autoComplete="off" />
      </label>
      <label className="bx-field">Camera type
        <select className="bx-input" value={form.type} onChange={set('type')}>
          <option value="rtsp">IP / RTSP camera (with credentials)</option>
          <option value="webcam">Local webcam (device)</option>
          <option value="upload">Upload a video file</option>
          <option value="folder">Browse a video already on the server</option>
        </select>
      </label>
      {form.type === 'rtsp' && (
        <>
          <label className="bx-field">RTSP / HTTP URL
            <input className="bx-input" value={form.source} onChange={set('source')} placeholder="rtsp://192.168.1.50:554/stream1" autoComplete="off" />
          </label>
          <div className="bx-field-row">
            <label className="bx-field">Username <input className="bx-input" value={form.user} onChange={set('user')} autoComplete="off" /></label>
            <label className="bx-field">Password <input className="bx-input" type="password" value={form.pass} onChange={set('pass')} autoComplete="new-password" /></label>
          </div>
          <div className="bx-hint">The password is stored on the server and is never shown again, in the UI or in any API response.</div>
        </>
      )}
      {form.type === 'webcam' && (
        <label className="bx-field">Device index <input className="bx-input" value={form.source} onChange={set('source')} /></label>
      )}
      {form.type === 'upload' && (
        <label className="bx-field">Video file
          <input className="bx-input" type="file" accept="video/*" onChange={(e) => setFile(e.target.files[0] || null)} />
        </label>
      )}
      {form.type === 'folder' && (
        <label className="bx-field">Choose a server video
          <select className="bx-input" value={picked} onChange={(e) => setPicked(e.target.value)}>
            {browse.state === 'loading' && <option value="">Loading…</option>}
            {browse.state === 'error' && <option value="">Could not load the list - is the Face Mask service running?</option>}
            {browse.state === 'ok' && !browse.files.length && <option value="">No videos found</option>}
            {browse.state === 'ok' && browse.files.length > 0 && <option value="">Select a video…</option>}
            {browse.files.map((f) => <option key={f.path} value={f.path}>{f.name} ({f.folder})</option>)}
          </select>
        </label>
      )}
      <label className="bx-field" style={{ marginTop: 12 }}>Location / branch
        <input className="bx-input" value={form.location} onChange={set('location')} placeholder="e.g. Main branch, front gate" autoComplete="off" />
      </label>
    </Modal>
  );
}
