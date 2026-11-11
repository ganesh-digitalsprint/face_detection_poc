/** One request owner per cycle, independent of card mounts. Redux persists outcomes. */
export function createOpenTimerController({ read, write, request, isCurrent = () => true, scheduleRetry = () => {}, now = Date.now }) {
  const inFlight = new Set();
  return async function evaluate(m) {
    const elapsed = m.openWithoutCrossingSeconds;
    const threshold = m.openWithoutCrossingThresholdSeconds;
    const cycleId = `${m.gateSessionId}:${m.cycleStartedAt}`;
    let previous = read(m.gateSessionId, cycleId);
    if (m.gateState === 'FULLY_OPEN' && m.cycleStartedAt != null && !m.finalTimer
        && ['ACTIVE', 'PROCESSING'].includes(m.status) && !previous) {
      previous = { sessionId: m.gateSessionId, cycleId, status: 'COUNTING', wasActive: true };
      write(previous);
    }
    if (!isCurrent(m) || m.gateState !== 'FULLY_OPEN' || !m.gateSessionId || m.cycleStartedAt == null
        || !Number.isFinite(elapsed) || !(threshold > 0) || elapsed < threshold
        || (m.finalTimer && !previous?.wasActive && !previous?.payload)
        || previous?.status === 'ALERT_RAISED' || inFlight.has(cycleId)
        || (previous?.retryAt ?? 0) > now()
        || (!m.finalTimer && !['ACTIVE', 'PROCESSING'].includes(m.status))) return;
    const attempts = (previous?.attempts ?? 0) + 1;
    const payload = previous?.payload ?? {
      elapsed_seconds: elapsed, threshold_seconds: threshold,
      timer_cycle_id: cycleId, gate_session_id: m.gateSessionId,
      gate_state: m.gateState, entry_count: m.entryCount, exit_count: m.exitCount,
      video_timestamp_seconds: m.source === 'video' ? m.videoTimeSeconds : undefined,
    };
    inFlight.add(cycleId);
    write({ sessionId: m.gateSessionId, cycleId, status: 'ALERT_REQUEST_PENDING', wasActive: true, attempts, payload });
    try {
      const result = await request(m, payload);
      if (result?.alert_raised !== true) throw new Error('Backend has not confirmed the alert');
      write({ sessionId: m.gateSessionId, cycleId, status: 'ALERT_RAISED', wasActive: true, attempts, payload });
    } catch (error) {
      write({ sessionId: m.gateSessionId, cycleId, status: 'ALERT_REQUEST_FAILED', wasActive: true, attempts, payload,
        retryAt: now() + Math.min(30000, 1000 * 2 ** Math.min(attempts - 1, 5)), error: error.message });
      scheduleRetry(() => evaluate(m), Math.min(30000, 1000 * 2 ** Math.min(attempts - 1, 5)));
    } finally { inFlight.delete(cycleId); }
  };
}
