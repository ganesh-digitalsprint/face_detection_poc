let ctx = null;
export const soundOn = () => { try { return localStorage.getItem('bx-sound') !== 'off'; } catch { return true; } };
export const setSound = (on) => { try { localStorage.setItem('bx-sound', on ? 'on' : 'off'); } catch { /* ignore */ } };

/** Two-tone square beep used for zone alerts. Browsers block audio until the page was clicked once - that is fine. */
export function beep() {
  if (!soundOn()) return;
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    [0, 0.22].forEach((t) => {
      const o = ctx.createOscillator(); const g = ctx.createGain();
      o.type = 'square'; o.frequency.value = 880; g.gain.value = 0.08;
      o.connect(g); g.connect(ctx.destination);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.15);
    });
  } catch { /* audio not available */ }
}

/** Softer beep for site-wide high / critical events. */
export function eventBeep(severity) {
  if (!soundOn()) return;
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    const tone = (freq, ms, delay = 0) => setTimeout(() => {
      const o = ctx.createOscillator(); const g = ctx.createGain();
      o.type = 'sine'; o.frequency.value = freq; g.gain.value = 0.06;
      o.connect(g).connect(ctx.destination); o.start(); setTimeout(() => o.stop(), ms);
    }, delay);
    tone(severity === 'critical' ? 880 : 660, severity === 'critical' ? 260 : 160);
    if (severity === 'critical') tone(880, 220, 300);
  } catch { /* ignore */ }
}
