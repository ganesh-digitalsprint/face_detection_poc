import { useEffect, useRef, useSyncExternalStore } from 'react';
import { bxWsUrl } from './api/index.js';

// One shared websocket to /api/ws/alerts for every Branch Exterior page.
const listeners = { new_event: new Set(), connection: new Set() };
let socket = null;
let connected = false;
let retryMs = 1000;
let users = 0;
let retryTimer = null;

const emit = (type, payload) => listeners[type].forEach((cb) => { try { cb(payload); } catch (e) { console.error(e); } });
const setConnected = (v) => { connected = v; emit('connection', v); };

function connect() {
  if (socket || users === 0) return;
  const ws = new WebSocket(bxWsUrl());
  socket = ws;
  ws.onopen = () => { setConnected(true); retryMs = 1000; };
  ws.onclose = () => {
    if (socket === ws) socket = null;
    setConnected(false);
    if (users > 0) { retryTimer = setTimeout(connect, retryMs); retryMs = Math.min(retryMs * 1.5, 15000); }
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'new_event') emit('new_event', msg.event);
    } catch (e) { console.error('bad ws message', e); }
  };
}

function acquire() {
  users += 1;
  if (users === 1) connect();
  return () => {
    users -= 1;
    if (users === 0) {
      clearTimeout(retryTimer);
      const ws = socket; socket = null;
      if (ws) { ws.onclose = null; ws.close(); }
      setConnected(false);
    }
  };
}

/** Keep the feed alive while a component using it is mounted. */
export function useFeedConnection() {
  useEffect(() => acquire(), []);
}

/** Subscribe to "new_event" for the lifetime of the component. */
export function useNewEvents(callback) {
  const ref = useRef(callback);
  ref.current = callback;
  useEffect(() => {
    const fn = (e) => ref.current(e);
    listeners.new_event.add(fn);
    return () => listeners.new_event.delete(fn);
  }, []);
}

export function useFeedConnected() {
  return useSyncExternalStore(
    (cb) => { listeners.connection.add(cb); return () => listeners.connection.delete(cb); },
    () => connected,
  );
}
