import { useCallback, useEffect, useRef, useState } from 'react';
import { api, bxStorageUrl } from '../api/index.js';
import Modal from '../components/Modal.jsx';
import { Empty } from '../components/ui.jsx';

function EnrollModal({ onClose, onDone }) {
  const [name, setName] = useState('');
  const [emp, setEmp] = useState('');
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!name.trim()) { alert('Name is required.'); return; }
    setBusy(true);
    try {
      const guard = await api.post('/guards', { name: name.trim(), employee_id: emp.trim() });
      for (const file of files) { const fd = new FormData(); fd.append('file', file); await api.postForm(`/guards/${guard.id}/photo`, fd); }
      onClose(); onDone();
    } catch (e) { alert(`Could not enroll the guard: ${e.message}`); } finally { setBusy(false); }
  };
  return (
    <Modal title="Enroll a guard" onClose={onClose} footer={(
      <>
        <button type="button" className="bx-btn" onClick={onClose}>Cancel</button>
        <button type="button" className="bx-btn bx-btn-primary" disabled={busy} onClick={save}>{busy ? 'Enrolling…' : 'Enroll'}</button>
      </>
    )}>
      <label className="bx-field">Full name <input className="bx-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></label>
      <label className="bx-field">Employee ID (optional) <input className="bx-input" value={emp} onChange={(e) => setEmp(e.target.value)} /></label>
      <label className="bx-field">Face photo(s) - clear, front-facing works best
        <input className="bx-input" type="file" accept="image/*" multiple onChange={(e) => setFiles([...e.target.files])} />
      </label>
    </Modal>
  );
}

export default function GuardRosterPage() {
  const [guards, setGuards] = useState(null);
  const [recStatus, setRecStatus] = useState('checking recognizer...');
  const [enrollOpen, setEnrollOpen] = useState(false);
  const photoInput = useRef(null);
  const photoFor = useRef(null);

  const load = useCallback(async () => {
    try { setGuards(await api.get('/guards')); } catch (e) { alert(e.message); setGuards([]); }
    try {
      const s = await api.post('/guards/retrain');
      setRecStatus(s.recognizer_available ? `recognizer ready (${s.trained_faces} face image(s))` : 'recognizer unavailable on this build');
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const retrain = async () => {
    try { const r = await api.post('/guards/retrain'); alert(`Retrained on ${r.trained_faces} face image(s).`); } catch (e) { alert(e.message); }
    load();
  };
  const addPhoto = (id) => { photoFor.current = id; photoInput.current.click(); };
  const onPhoto = async (e) => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try { await api.postForm(`/guards/${photoFor.current}/photo`, fd); } catch (x) { alert(x.message); }
    load();
  };
  const remove = async (g) => {
    if (!confirm(`Remove guard "${g.name}"?`)) return;
    try { await api.del(`/guards/${g.id}`); } catch (e) { alert(e.message); }
    load();
  };

  return (
    <>
      <div className="bx-card bx-mb-16">
        <div className="bx-card-title">How this works</div>
        <p className="bx-muted">
          Face detection and recognition run fully offline using OpenCV&apos;s built-in Haar cascade and LBPH recognizer -
          no internet access or extra model download is needed. Enroll a guard with 2-3 clear photos of their face;
          the recognizer retrains automatically. On camera, a track whose face matches an enrolled guard is labelled{' '}
          <b>GUARD: name</b> instead of being treated as an unidentified person. This is a small, opt-in identity
          check for staff who explicitly enrolled - it is never used to identify members of the public.
        </p>
      </div>
      <div className="bx-section-title">
        <h2>Enrolled guards</h2>
        <div className="bx-row bx-gap-8 bx-wrap">
          <span className="bx-tag">{recStatus}</span>
          <button type="button" className="bx-btn" onClick={retrain}>↻ Retrain recognizer</button>
          <button type="button" className="bx-btn bx-btn-primary" onClick={() => setEnrollOpen(true)}>+ Enroll guard</button>
        </div>
      </div>
      {guards && guards.length === 0 && <Empty icon="🛡️">No guards enrolled yet.</Empty>}
      <div className="bx-grid bx-grid-3">
        {(guards || []).map((g) => (
          <div className="bx-card" key={g.id}>
            <div className="bx-guard">
              {g.photo_paths.length
                ? <img className="bx-photo" src={bxStorageUrl(g.photo_paths[0])} alt={g.name} />
                : <div className="bx-photo ph">{(g.name[0] || '?').toUpperCase()}</div>}
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{g.name}</div>
                <div className="bx-muted" style={{ fontSize: 12 }}>{g.employee_id || 'No ID set'}</div>
                <div className="bx-tag" style={{ marginTop: 4 }}>{g.photo_paths.length} photo{g.photo_paths.length === 1 ? '' : 's'} enrolled</div>
              </div>
            </div>
            <div className="bx-thumbs">{g.photo_paths.map((p) => <img key={p} src={bxStorageUrl(p)} alt="" />)}</div>
            <div className="bx-row bx-gap-8 bx-wrap" style={{ paddingTop: 12 }}>
              <button type="button" className="bx-btn bx-btn-sm" onClick={() => addPhoto(g.id)}>+ Add photo</button>
              <button type="button" className="bx-btn bx-btn-sm bx-btn-ghost" onClick={() => remove(g)}>Remove</button>
            </div>
          </div>
        ))}
      </div>
      <input ref={photoInput} type="file" accept="image/*" hidden onChange={onPhoto} />
      {enrollOpen && <EnrollModal onClose={() => setEnrollOpen(false)} onDone={load} />}
    </>
  );
}
