import { useCallback, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useNewEvents } from '../feed.js';
import { eventBeep } from '../sound.js';

/** Site-wide (all Branch Exterior pages) toast + beep for every new alert. */
export default function Toasts({ onEvent }) {
  const [items, setItems] = useState([]);
  const nextId = useRef(1);
  const navigate = useNavigate();

  const remove = useCallback((id) => setItems((xs) => xs.filter((x) => x.id !== id)), []);

  useNewEvents((event) => {
    const id = nextId.current++;
    setItems((xs) => [...xs, { id, event }]);
    setTimeout(() => remove(id), 9000);
    if (event.severity === 'critical' || event.severity === 'high') eventBeep(event.severity);
    onEvent?.(event);
  });

  return (
    <div className="bx-toast-root bx-page">
      {items.map(({ id, event }) => (
        <div
          key={id}
          className="bx-toast"
          style={{ borderLeftColor: `var(--bx-sev-${event.severity || 'medium'})` }}
          onClick={() => { remove(id); navigate(`/branch-exterior/dashboard?event=${event.id}`); }}
        >
          <div className="t-title">
            <span>{event.camera_name || 'Camera'}</span>
            <span className={`bx-badge sev-${event.severity}`}>{event.severity}</span>
          </div>
          <div className="t-msg">{event.message || event.scenario}</div>
        </div>
      ))}
    </div>
  );
}
