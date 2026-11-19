export function playFaceMaskAlertTone() {
  try {
    const context = new AudioContext();
    const tone = context.createOscillator();
    tone.frequency.value = 700;
    tone.connect(context.destination);
    tone.start();
    tone.stop(context.currentTime + 0.15);
    tone.onended = () => context.close();
  } catch { /* Sound is optional and may be blocked until a click. */ }
}
