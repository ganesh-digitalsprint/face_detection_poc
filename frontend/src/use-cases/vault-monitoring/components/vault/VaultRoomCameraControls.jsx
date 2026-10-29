import { useState } from 'react';
import { Cctv, Play, Square, Webcam } from 'lucide-react';

const button = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-50';
const field = 'mt-1 min-h-11 w-full rounded-lg border border-[#C8CEDB] bg-white px-3 font-normal text-[#0F1B3D] outline-none focus-visible:border-[#34479B] focus-visible:ring-2 focus-visible:ring-[#34479B]/20';

export default function VaultRoomCameraControls({ camera, counting }) {
  const [source, setSource] = useState('webcam');
  const [name, setName] = useState('Vault Room Camera');
  const [mode, setMode] = useState('details');
  const [protocol, setProtocol] = useState('rtsp');
  const [host, setHost] = useState('');
  const [port, setPort] = useState('554');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [channel, setChannel] = useState('101');
  const [path, setPath] = useState('');
  const [url, setUrl] = useState('');
  const [formError, setFormError] = useState('');
  const busy = ['starting', 'connecting', 'reconnecting', 'stopping'].includes(camera.status);
  const connected = ['ready', 'connected', 'streaming'].includes(camera.status);
  const statusText = camera.status === 'streaming' || (camera.status === 'ready' && counting?.status === 'running') ? 'Tracking' : ['ready', 'connected'].includes(camera.status) ? 'Connected'
    : camera.status === 'reconnecting' ? 'Reconnecting' : camera.status === 'stopping' ? 'Stopping'
      : ['starting', 'connecting'].includes(camera.status) ? 'Connecting' : camera.status === 'error' ? 'Connection failed' : 'Disconnected';
  const statusClass = connected ? 'bg-[#E6F6EE] text-[#0B6B43]' : camera.status === 'error'
    ? 'bg-[#FDE9E7] text-[#B3261E]' : 'bg-slate-100 text-[#55607A]';

  const connectRtsp = (event) => {
    event.preventDefault();
    let submitted;
    try {
      if (mode === 'url') {
        submitted = url.trim();
      } else {
        const cleanHost = host.trim().replace(/^\[|\]$/g, '');
        const numericPort = Number(port);
        if (!cleanHost || /[\s/@?#]/.test(cleanHost) || !Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) throw new Error();
        const urlHost = cleanHost.includes(':') ? `[${cleanHost}]` : cleanHost;
        const auth = username ? `${encodeURIComponent(username)}${password ? `:${encodeURIComponent(password)}` : ''}@` : '';
        const streamPath = path.trim() || `/Streaming/Channels/${channel.trim()}`;
        submitted = `${protocol}://${auth}${urlHost}:${numericPort}${streamPath.startsWith('/') ? streamPath : `/${streamPath}`}`;
      }
      const parsed = new URL(submitted);
      if (!/^rtsps?:$/i.test(parsed.protocol) || !parsed.hostname || /\s/.test(submitted)) throw new Error();
    } catch {
      setFormError(mode === 'url'
        ? 'Enter a valid RTSP or RTSPS URL with the camera address and stream path.'
        : 'Check the camera IP/host, port, channel, and stream path.');
      return;
    }
    setFormError('');
    camera.startRtsp(name, submitted);
  };

  return <div className="space-y-3">
    <div className="flex flex-wrap items-center gap-3">
      <div role="group" aria-label="Vault Room camera source" className="inline-flex rounded-xl bg-[#F4F6FB] p-1">
        <button type="button" aria-pressed={source === 'webcam'} disabled={busy || connected}
          onClick={() => { setSource('webcam'); setFormError(''); }}
          className={`${button} ${source === 'webcam' ? 'bg-[#34479B] text-white shadow-sm' : 'text-[#55607A] hover:bg-white'}`}>
          <Webcam className="h-4 w-4" aria-hidden />Webcam
        </button>
        <button type="button" aria-pressed={source === 'rtsp'} disabled={busy || connected}
          onClick={() => { setSource('rtsp'); setFormError(''); }}
          className={`${button} ${source === 'rtsp' ? 'bg-[#34479B] text-white shadow-sm' : 'text-[#55607A] hover:bg-white'}`}>
          <Cctv className="h-4 w-4" aria-hidden />CCTV
        </button>
      </div>
      <span role="status" className={`rounded-full px-3 py-1.5 text-xs font-bold ${statusClass}`}>{statusText}</span>
      {connected && <button type="button" onClick={camera.stop} className={`${button} ml-auto border border-[#E3E7F0] bg-white text-[#B3261E] hover:bg-red-50`}>
        <Square className="h-4 w-4" aria-hidden />Stop camera
      </button>}
    </div>

    {!connected && source === 'webcam' && <div className="grid gap-3 rounded-xl border border-[#E3E7F0] bg-white p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
      <label className="text-sm font-semibold text-[#0F1B3D]">Camera name
        <input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} className={field} />
      </label>
      <button type="button" disabled={busy} onClick={() => camera.startWebcam(name)}
        className={`${button} bg-[#34479B] text-white hover:bg-[#293A82]`}>
        <Play className="h-4 w-4" aria-hidden />{camera.status === 'error' ? 'Retry webcam' : 'Connect webcam'}
      </button>
      <p className="text-xs text-[#66718A]">Uses the webcam selected by your browser's camera permission prompt.</p>
    </div>}

    {!connected && source === 'rtsp' && <form onSubmit={connectRtsp} className="rounded-xl border border-[#E3E7F0] bg-white p-4 sm:p-5">
      <div className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div><h3 className="text-sm font-bold text-[#0F1B3D]">Connect a Vault Room CCTV camera</h3>
          <p className="mt-1 text-sm text-[#55607A]">Enter the full RTSP link or build it from the camera's IP and channel.</p></div>
        <label className="w-full text-sm font-semibold text-[#0F1B3D] sm:w-64">Connection method
          <select value={mode} onChange={(event) => { setMode(event.target.value); setFormError(''); }} className={field}>
            <option value="details">IP address and channel</option>
            <option value="url">Full RTSP URL</option>
          </select>
        </label>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm font-semibold text-[#0F1B3D]">Camera name
          <input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} className={field} placeholder="Vault Room Camera" />
        </label>
        {mode === 'url' ? <label className="text-sm font-semibold text-[#0F1B3D] sm:col-span-2">RTSP stream URL
          <input required type="password" autoComplete="off" spellCheck="false" value={url} onChange={(event) => setUrl(event.target.value)} className={field} placeholder="rtsp://user:password@192.168.1.50:554/stream" />
          <span className="mt-1 block text-xs font-normal text-[#66718A]">RTSP credentials are sent to the backend and are not included in camera status.</span>
        </label> : <>
          <label className="text-sm font-semibold text-[#0F1B3D]">Protocol
            <select value={protocol} onChange={(event) => setProtocol(event.target.value)} className={field}><option value="rtsp">RTSP</option><option value="rtsps">RTSPS</option></select>
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Camera IP address or host
            <input required value={host} onChange={(event) => setHost(event.target.value)} autoComplete="off" className={field} placeholder="192.168.1.50" />
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Port
            <input required type="number" min="1" max="65535" value={port} onChange={(event) => setPort(event.target.value)} className={field} />
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Username <span className="font-normal text-[#66718A]">(optional)</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" className={field} />
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Password <span className="font-normal text-[#66718A]">(optional)</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" className={field} />
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D]">Channel
            <input required value={channel} onChange={(event) => setChannel(event.target.value)} className={field} placeholder="101" />
            <span className="mt-1 block text-xs font-normal text-[#66718A]">Common default path: /Streaming/Channels/{channel || '101'}.</span>
          </label>
          <label className="text-sm font-semibold text-[#0F1B3D] sm:col-span-2 lg:col-span-3">Custom stream path <span className="font-normal text-[#66718A]">(optional)</span>
            <input value={path} onChange={(event) => setPath(event.target.value)} className={field} placeholder="Leave blank to use the channel path, or enter /path/to/stream" />
          </label>
        </>}
      </div>
      {formError && <p role="alert" className="mt-3 text-sm font-medium text-[#B3261E]">{formError}</p>}
      <div className="mt-4 flex flex-col justify-between gap-3 border-t border-[#E3E7F0] pt-4 sm:flex-row sm:items-center">
        <p className="text-xs text-[#66718A]">The backend host needs network access to the camera.</p>
        <button type="submit" disabled={busy || (mode === 'url' ? !url.trim() : !host.trim())} className={`${button} bg-[#34479B] text-white hover:bg-[#293A82]`}>
          <Cctv className="h-4 w-4" aria-hidden />{busy ? 'Connecting...' : camera.status === 'error' ? 'Retry CCTV' : 'Connect CCTV'}
        </button>
      </div>
    </form>}
    {busy && <p role="status" className="text-sm text-[#55607A]">{statusText} camera source...</p>}
    {connected && camera.status === 'connected' && <p className="text-sm text-[#55607A]">Camera connected; waiting for the first processed frame.</p>}
  </div>;
}
