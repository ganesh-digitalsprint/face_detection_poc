import { useEffect, useRef, useState } from 'react';
import { formatClock } from '../grillGateModel.js';
import { StatCard } from './ui.jsx';

/** Counts one confirmed FULLY_OPEN episode, independent of crossing activity. */
export default function GateOpenCard(props) {
  if (props.monitoring?.source === 'video') {
    const { monitoring, gateState } = props;
    const elapsed = monitoring.gateOpenSeconds;
    const sub = elapsed == null ? 'Video time \u00b7 Timer unavailable'
      : monitoring.finalTimer ? 'Video time \u00b7 Final duration'
        : gateState === 'FULLY_OPEN' ? 'Video time \u00b7 Gate is fully open'
          : 'Video time \u00b7 Gate is no longer fully open';
    return <StatCard label="Gate open" value={elapsed == null ? '\u2014' : formatClock(elapsed)}
      valueClass="text-[#0F1B3D]" sub={sub} />;
  }
  return <LiveGateOpenCard {...props} />;
}

function LiveGateOpenCard({ gateState, gateDirection, sessionId, paused = false }) {
  const intervalRef = useRef(null);
  const startedAtRef = useRef(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(null);

  useEffect(() => {
    const closing = gateState === 'CLOSED'
      || (gateState === 'PARTIALLY_OPEN' && String(gateDirection).toUpperCase() === 'CLOSING');
    if (closing && startedAtRef.current != null) {
      setElapsedSeconds(Math.floor((Date.now() - startedAtRef.current) / 1000));
      startedAtRef.current = null;
    }
    if (gateState === 'FULLY_OPEN' && !paused && startedAtRef.current == null) {
      startedAtRef.current = Date.now();
      setElapsedSeconds(0);
    }
    if (startedAtRef.current == null) {
      return undefined;
    }
    if (paused) {
      setElapsedSeconds(Math.floor((Date.now() - startedAtRef.current) / 1000));
      return undefined;
    }

    const updateElapsed = () => {
      if (startedAtRef.current != null) {
        setElapsedSeconds(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }
    };
    intervalRef.current = window.setInterval(updateElapsed, 1000);
    const timerId = intervalRef.current;
    return () => {
      window.clearInterval(timerId);
      if (intervalRef.current === timerId) intervalRef.current = null;
    };
  }, [gateState, gateDirection, sessionId, paused]);

  const active = startedAtRef.current != null;
  const value = elapsedSeconds == null ? '\u2014' : formatClock(elapsedSeconds);
  const sub = active && paused ? 'Paused after video processing'
      : active ? 'Counting while gate is open' : 'Waiting for fully open';
  return <StatCard label="Gate open" value={value} valueClass="text-[#0F1B3D]" sub={sub} />;
}
