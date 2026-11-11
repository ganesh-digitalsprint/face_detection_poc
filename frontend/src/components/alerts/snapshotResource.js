/** Own one authenticated binary snapshot and release it on source changes/unmount. */
export function loadSnapshot({ ref, fetchBlob, onChange, urls = URL }) {
  const controller = new AbortController();
  let active = true;
  let url;
  onChange({ loading: true, url: '', error: '' });
  Promise.resolve().then(() => fetchBlob(ref, controller.signal)).then((blob) => {
    if (!active) return;
    url = urls.createObjectURL(blob);
    onChange({ loading: false, url, error: '' });
  }).catch(() => {
    if (active) onChange({ loading: false, url: '', error: 'Snapshot could not be retrieved.' });
  });
  return () => { active = false; controller.abort(); if (url) urls.revokeObjectURL(url); };
}
