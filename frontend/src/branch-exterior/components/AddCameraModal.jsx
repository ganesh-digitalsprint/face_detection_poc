import { useEffect, useState } from 'react';
import { api } from '../api.js';
import Modal from './Modal.jsx';

/** Shared by Live Monitoring and Regions & Zones: register an RTSP / webcam / uploaded / server video. */
export default function AddCameraModal({ onClose, onCreated, start = true }) {
  const [name, setName] = useState('');
  const [type, setType] = useState('rtsp');
  const [location, setLocation] = useState('');
  const [source, setSource] = useState('');
  const [user, setUser] = useState('');
  const [pass, setPass] = useState('');
  const [file, setFile] = useState(null);
  const [browse, setBrowse] = useState({ state: 'idle', files: [] });
  const [picked, setPicked] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { setSource(type === 'webcam' ? '0' : ''); }, [type]);

  useEffect(() => {
    if (type !== 'folder') return undefined;
    let stale = false;
    setBrowse({ state: 'loading', files: [] });
    api.get('/uploads/browse')
      .then((r) => { if (!stale) setBrowse({ state: 'ok', files: r.files || [] }); })
      .catch(() => { if (!stale) setBrowse({ state: 'error', files: [] }); });
    return () => { stale = true; };
  }, [type]);

  const submit = async () => {
    if (!name.trim()) { alert("Please give the camera a name - this is how you'll tell it apart on Live Monitoring, the Dashboard, and in every alert."); return; }
    let src = ''; let username = ''; let password = '';
    setBusy(true);
    try {
      if (type === 'rtsp') {
        src = source.trim();
        if (!src) { alert('Please enter the RTSP/HTTP URL.'); return; }
        username = user.trim(); password = pass.trim();
      } else if (type === 'webcam') {
        src = source.trim() || '0';
      } else if (type === 'upload') {
        if (!file) { alert('Please choose a video file.'); return; }
        const fd = new FormData(); fd.append('file', file);
        src = (await api.postForm('/uploads/video', fd)).path;
      } else {
        src = picked;
        if (!src) { alert('Please pick a video from the list (if the list is empty, add a file to storage/sample_videos and reopen this dialog).'); return; }
      }
      const created = await api.post(start === false ? '/cameras?start=false' : '/cameras', {
        name: name.trim(), cam_type: type, source: src, username, password, location: location.trim(), enabled: true, loop_video: true,
      });
      onClose();
      if (onCreated) await onCreated(created);
    } catch (e) {
      alert(`Could not add camera: ${e.message}`);
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
      <label className="bx-field">Camera name
        <input className="bx-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Main Entrance Exterior" autoComplete="off" />
      </label>
      <label className="bx-field">Camera type
        <select className="bx-input" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="rtsp">IP / RTSP camera (with credentials)</option>
          <option value="webcam">Local webcam (device)</option>
          <option value="upload">Upload a video file</option>
          <option value="folder">Browse a video already on the server</option>
        </select>
      </label>
      {type === 'rtsp' && (
        <>
          <label className="bx-field">RTSP / HTTP URL
            <input className="bx-input" value={source} onChange={(e) => setSource(e.target.value)} placeholder="rtsp://192.168.1.50:554/stream1" />
          </label>
          <div className="bx-field-row">
            <label className="bx-field">Username <input className="bx-input" value={user} onChange={(e) => setUser(e.target.value)} /></label>
            <label className="bx-field">Password <input className="bx-input" type="password" value={pass} onChange={(e) => setPass(e.target.value)} /></label>
          </div>
        </>
      )}
      {type === 'webcam' && (
        <label className="bx-field">Device index <input className="bx-input" value={source} onChange={(e) => setSource(e.target.value)} /></label>
      )}
      {type === 'upload' && (
        <>
          <label className="bx-field">Video file <input className="bx-input" type="file" accept="video/*" onChange={(e) => setFile(e.target.files[0] || null)} /></label>
          <div className="bx-hint">The file is uploaded to the server&apos;s storage folder and looped continuously. This is your actual footage - it is always what gets analysed and streamed, never a demo scene.</div>
        </>
      )}
      {type === 'folder' && (
        <>
          <label className="bx-field">Choose a server video
            <select className="bx-input" value={picked} onChange={(e) => setPicked(e.target.value)}>
              {browse.state === 'loading' && <option value="">Loading...</option>}
              {browse.state === 'error' && <option value="">Could not load the video list - check the server is running</option>}
              {browse.state === 'ok' && !browse.files.length && <option value="">No videos found - add files to storage/sample_videos first</option>}
              {browse.state === 'ok' && browse.files.length > 0 && <option value="">Select a video...</option>}
              {browse.files.map((f) => <option key={f.path} value={f.path}>{f.name} ({f.source})</option>)}
            </select>
          </label>
          <div className="bx-hint">Lists files from backend/storage/sample_videos and backend/storage/uploads. If nothing appears, confirm the file is actually in one of those folders, then reopen this dialog.</div>
        </>
      )}
      <label className="bx-field" style={{ marginTop: 12 }}>Location / notes
        <input className="bx-input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Rear car park, north wall" autoComplete="off" />
      </label>
    </Modal>
  );
}

/** "Rescan videos folder" button behaviour (shared). */
export async function rescanVideosFolder(setBusy, after) {
  setBusy(true);
  try {
    const r = await api.post('/cameras/sync-folder');
    if (r.count > 0) alert(`Created ${r.count} new camera(s): ${r.created.join(', ')}`);
    else alert('No new videos found in storage/sample_videos - every file is already in the list.');
    if (after) await after();
  } catch (e) {
    alert(`Rescan failed: ${e.message}`);
  } finally { setBusy(false); }
}
