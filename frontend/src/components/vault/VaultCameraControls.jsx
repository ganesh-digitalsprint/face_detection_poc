import { useState } from 'react';
import { Cctv, RotateCcw, Square, Video, Webcam } from 'lucide-react';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';

const SOURCES = [
  { kind: CAMERA_KINDS.WEBCAM, label: 'Webcam', icon: Webcam },
  { kind: CAMERA_KINDS.CCTV, label: 'CCTV', icon: Cctv },
];
const base = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-50';
const segment = (active) => `${base} ${active ? 'bg-[#34479B] text-white shadow-sm' : 'text-[#55607A] hover:bg-white'}`;
const secondary = `${base} border border-[#E3E7F0] bg-white text-[#0F1B3D] hover:bg-slate-50`;
const danger = `${base} bg-[#B3261E] text-white hover:bg-[#931F18]`;
const primary = `${base} bg-[#34479B] text-white hover:bg-brand-dark`;
const input = 'mt-1 min-h-11 w-full rounded-lg border border-[#C8CEDB] bg-white px-3 font-normal text-[#0F1B3D] outline-none focus-visible:border-[#34479B] focus-visible:ring-2 focus-visible:ring-[#34479B]/20';

/** Camera source picker and access-session actions. */
export default function VaultCameraControls({ camera, sessionActive, sessionStarted, onRestart, onStop, vault }) {
  const [source, setSource] = useState(camera.kind ?? CAMERA_KINDS.WEBCAM);
  const [connectionMode, setConnectionMode] = useState('parts');
  const [name, setName] = useState('Entrance CCTV');
  const [protocol, setProtocol] = useState('rtsp');
  const [host, setHost] = useState('');
  const [port, setPort] = useState('554');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [channel, setChannel] = useState('101');
  const [streamPath, setStreamPath] = useState('');
  const [rtspUrl, setRtspUrl] = useState('');
  const [formError, setFormError] = useState('');
  const cameraOn = camera.status === 'starting' || camera.status === 'ready';
  const selected = camera.kind ?? source;
  const busy = camera.status === 'starting';

  const choose = (kind) => {
    setSource(kind);
    setFormError('');
    if (cameraOn && kind !== camera.kind) {
      camera.stop();
      if (kind === CAMERA_KINDS.WEBCAM) camera.start(kind);
    }
  };

  const connectCctv = (event) => {
    event.preventDefault();
    let url;
    try {
      if (connectionMode === 'url') {
        url = rtspUrl.trim();
      } else {
        const cleanHost = host.trim().replace(/^\[|\]$/g, '');
        if (!cleanHost || /[\s/@?#]/.test(cleanHost)) throw new Error();
        const numericPort = Number(port);
        if (!Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) throw new Error();
        const urlHost = cleanHost.includes(':') ? `[${cleanHost}]` : cleanHost;
        const credentials = username ? `${encodeURIComponent(username)}${password ? `:${encodeURIComponent(password)}` : ''}@` : '';
        const defaultPath = `/Streaming/Channels/${channel.trim()}`;
        const path = streamPath.trim() || defaultPath;
        url = `${protocol}://${credentials}${urlHost}:${numericPort}${path.startsWith('/') ? path : `/${path}`}`;
      }
      const parsed = new URL(url);
      if (!/^rtsps?:$/i.test(parsed.protocol) || !parsed.hostname || /\s/.test(url)) throw new Error();
    } catch {
      setFormError(connectionMode === 'url'
        ? 'Enter a valid RTSP or RTSPS URL, including the camera address and stream path.'
        : 'Check the camera IP/host, port, channel, and stream path.');
      return;
    }
    setFormError('');
    camera.start(CAMERA_KINDS.CCTV, { rtspUrl: url });
  };

  return <div className="space-y-4">
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <div role="group" aria-label="Camera source" className="inline-flex self-start rounded-xl bg-[#F4F6FB] p-1">
        {SOURCES.map(({ kind, label, icon: Icon }) => (
          <button key={kind} type="button" className={segment(selected === kind)} aria-pressed={selected === kind}
            disabled={sessionActive || busy} onClick={() => choose(kind)}>
            <Icon className="h-4 w-4" aria-hidden />{label}
          </button>
        ))}
      </div>

      {sessionActive && vault.config?.allow_mode_select && (
        <label className="flex min-h-11 items-center gap-2 text-sm font-medium text-[#55607A]">
          Required custodians:
          <select aria-label="Required custodians" value={vault.selectedRequiredPersons ?? vault.config.required_persons}
            disabled className="min-h-9 rounded border border-slate-300 bg-slate-100 px-2">
            <option value={1}>1</option><option value={2}>2</option>
          </select>
        </label>
      )}

      <div className="flex flex-wrap gap-2 sm:ml-auto">
        {cameraOn ? <>
          <button type="button" className={secondary} disabled={!sessionStarted || vault.roomBlocked}
            title={vault.roomBlocked ? 'Vault room session is active' : undefined}
            aria-describedby={vault.roomBlocked ? 'vault-room-restart-disabled' : undefined} onClick={onRestart}>
            <RotateCcw className="h-4 w-4" aria-hidden />Restart session
          </button>
          <button type="button" className={danger} onClick={onStop}><Square className="h-4 w-4" aria-hidden />Stop camera</button>
        </> : selected === CAMERA_KINDS.WEBCAM ? (
          <button type="button" className={primary} disabled={busy} onClick={() => camera.start(CAMERA_KINDS.WEBCAM)}>
            <Video className="h-4 w-4" aria-hidden />{camera.status === 'error' ? 'Retry camera' : 'Start camera'}
          </button>
        ) : null}
      </div>
    </div>

    {selected === CAMERA_KINDS.CCTV && !cameraOn && <form onSubmit={connectCctv} className="rounded-xl border border-[#E3E7F0] bg-[#F8F9FC] p-4 sm:p-5">
      <div className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div><h3 className="text-sm font-bold text-[#0F1B3D]">Connect an IP camera</h3>
          <p className="mt-1 text-sm text-[#55607A]">Enter an RTSP link or build one from your camera's network details.</p></div>
        <label className="w-full text-sm font-medium text-[#55607A] sm:w-64">Connection method
          <select value={connectionMode} onChange={(event) => { setConnectionMode(event.target.value); setFormError(''); }} className={input}>
            <option value="parts">IP address and channel</option>
            <option value="url">Full RTSP URL</option>
          </select>
        </label>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm font-semibold text-[#0F1B3D]">Camera name
          <input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} className={input} placeholder="Entrance CCTV" />
        </label>
        {connectionMode === 'url' ? <label className="text-sm font-semibold text-[#0F1B3D] sm:col-span-2 lg:col-span-2">RTSP URL
          <input required value={rtspUrl} onChange={(event) => setRtspUrl(event.target.value)} className={input} type="password" autoComplete="off" spellCheck="false" placeholder="rtsp://user:password@192.168.1.50:554/stream" />
          <span className="mt-1 block text-xs font-normal text-[#66718A]">Your URL and credentials are sent securely to the backend and are not shown in camera status.</span>
        </label> : <>
          <label className="text-sm font-semibold text-[#0F1B3D]">Protocol
            <select value={protocol} onChange={(event) => setProtocol(event.target.value)} className={input}>
              <option value="rtsp">RTSP</option><option value="rtsps">RTSPS</option>
            </select>
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Camera IP address or host
            <input required value={host} onChange={(event) => setHost(event.target.value)} className={input} autoComplete="off" placeholder="192.168.1.50" />
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Port
            <input required type="number" min="1" max="65535" value={port} onChange={(event) => setPort(event.target.value)} className={input} placeholder="554" />
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Username <span className="font-normal text-[#66718A]">(optional)</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} className={input} autoComplete="off" />
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Password <span className="font-normal text-[#66718A]">(optional)</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} className={input} autoComplete="new-password" />
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Channel number
            <input required value={channel} onChange={(event) => setChannel(event.target.value)} className={input} placeholder="101" />
            <span className="mt-1 block text-xs font-normal text-[#66718A]">Default path uses the common /Streaming/Channels/{channel || '101'} format.</span>
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D] sm:col-span-2 lg:col-span-3">Custom stream path <span className="font-normal text-[#66718A]">(optional)</span>
            <input value={streamPath} onChange={(event) => setStreamPath(event.target.value)} className={input} placeholder="Leave blank to use the channel path, or enter /path/to/stream" />
          </label>
        </>}
      </div>
      {formError && <p role="alert" className="mt-3 text-sm font-medium text-[#B3261E]">{formError}</p>}
      {camera.error && <p role="alert" className="mt-3 text-sm font-medium text-[#B3261E]">{camera.error}</p>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[#E3E7F0] pt-4">
        <p className="text-xs text-[#66718A]">The backend must be able to reach the camera on your network.</p>
        <button type="submit" className={primary} disabled={busy || (connectionMode === 'url' ? !rtspUrl.trim() : !host.trim())}>
          <Cctv className="h-4 w-4" aria-hidden />{busy ? 'Connecting...' : camera.status === 'error' ? 'Retry CCTV' : 'Connect CCTV'}
        </button>
      </div>
    </form>}

    {camera.status === 'error' && selected === CAMERA_KINDS.WEBCAM && <p role="alert" className="text-sm font-medium text-[#B3261E]">{camera.error}</p>}
    {busy && <p role="status" className="text-sm text-[#55607A]">Connecting to camera...</p>}
    {sessionStarted && vault.roomBlocked && <p id="vault-room-restart-disabled" className="text-sm text-[#55607A]">Vault room session is active</p>}
  </div>;
}
