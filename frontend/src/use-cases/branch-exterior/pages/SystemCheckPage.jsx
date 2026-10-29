import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, BX_BASE, bxUrl } from '../api/index.js';

const PAGE_BUILD = 10;
const Code = ({ children }) => <code>{children}</code>;

export default function SystemCheckPage() {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const out = [];
      const add = (kind, title, detail) => out.push({ kind, title, detail });
      const done = () => alive && setRows([...out]);
      let h = null;
      try { h = await api.get('/health'); } catch (e) {
        add('bad', 'Server not reachable', <>Is it running? Start it with <Code>python -m uvicorn app.main:app --port 8011</Code> in backend/use_cases/branch_exterior. ({e.message})</>);
        done(); return;
      }
      add('ok', 'Server is running', <>database: <Code>{h.db_engine}</Code> · address: <Code>{BX_BASE}</Code></>);
      if (!h.build || h.build < PAGE_BUILD) add('bad', `Server files are older than this page (server build ${h.build || 'unknown'}, page build ${PAGE_BUILD})`, <>Copy the latest <Code>backend</Code> files over the project the server runs from, then restart it.</>);
      else add('ok', `Server and pages match (build ${h.build})`, '');
      if (h.zone_schema) {
        if (h.zone_schema.ok && (h.zone_schema.modes || []).includes('suspicious')) add('ok', 'Zone settings accept all 4 alert rules', <Code>{h.zone_schema.modes.join(', ')}</Code>);
        else add('bad', 'Zone settings on the server are out of date', <>Replace <Code>backend/app/schemas/zone.py</Code> and restart. {h.zone_schema.error ? <Code>{h.zone_schema.error}</Code> : null}</>);
      }
      if (h.missing_routes && h.missing_routes.length) add('bad', 'API routes missing on the server', <>{h.missing_routes.map((r) => <Code key={r}>{r} </Code>)}<br />Copy the latest <Code>backend/app/main.py</Code> and restart.</>);
      else add('ok', `All ${h.routes_checked} required API routes are registered`, 'Zones, cameras, events, streams and reports are all reachable.');

      try {
        const cams = await api.get('/cameras');
        add(cams.length ? 'ok' : 'warn', `${cams.length} video(s)/camera(s) registered`, cams.map((c) => c.name).join(', ') || <>Put a video in <Code>backend/storage/sample_videos</Code> or use Add camera.</>);
        if (cams.length) {
          const info = await api.get(`/cameras/${cams[0].id}/prep`);
          if (info.ok) {
            add('ok', `Can read "${cams[0].name}"`, <>{info.source_w}x{info.source_h}, crop box <Code>{info.crop.join(', ')}</Code>{info.prep ? ` (${info.prep})` : ''}</>);
            if (info.video_url) {
              const r = await fetch(bxUrl(info.video_url), { method: 'HEAD' });
              add(r.ok ? 'ok' : 'bad', 'Video file is downloadable by the browser', <><Code>{info.video_url}</Code> -&gt; HTTP {r.status}</>);
            }
          } else add('bad', `Cannot read "${cams[0].name}"`, info.error);
          const z = await api.get(`/zones?camera_id=${cams[0].id}`);
          add('ok', `Zones API works (${z.length} zone(s) on "${cams[0].name}")`, '');
        }
      } catch (e) { add('bad', 'A request failed', e.message); }

      const can = document.createElement('video').canPlayType('video/mp4; codecs="avc1.42E01E"');
      add(can ? 'ok' : 'warn', 'This browser can play H.264 MP4 video', can ? 'Videos will play on the Regions page.' : 'Videos will fall back to still pictures.');
      done();
    })();
    return () => { alive = false; };
  }, []);

  return (
    <div className="bx-card" style={{ maxWidth: 900 }}>
      <p className="bx-muted">Open this page when something does not work. Take a screenshot of it and send it along.</p>
      {!rows && <div className="bx-row bx-gap-8 bx-muted" style={{ padding: 20 }}><span className="bx-spinner" /> Checking...</div>}
      {rows && rows.map((r, i) => (
        <div className="bx-sysrow" key={i}>
          <div className={`st ${r.kind}`}>{r.kind === 'ok' ? 'OK' : r.kind === 'bad' ? 'PROBLEM' : 'NOTE'}</div>
          <div><b>{r.title}</b><div className="bx-muted" style={{ fontSize: 13, marginTop: 2 }}>{r.detail}</div></div>
        </div>
      ))}
      <p className="bx-muted" style={{ marginTop: 18 }}>
        <Link to="/branch-exterior/live" style={{ color: 'var(--bx-brand)' }}>Live Monitoring</Link> · <Link to="/regions" style={{ color: 'var(--bx-brand)' }}>Regions &amp; Zones</Link> · <Link to="/alerts/branch" style={{ color: 'var(--bx-brand)' }}>Branch events</Link>
      </p>
    </div>
  );
}
