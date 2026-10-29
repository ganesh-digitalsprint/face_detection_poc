import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Captured still frames, kept per camera source so images from different
 * sources are never mixed. Owns the object URLs and revokes them on removal/unmount.
 */
export default function useCapturedFrames() {
  const [frames, setFrames] = useState({});
  const latest = useRef(frames);
  const counter = useRef(0);
  latest.current = frames;

  const add = useCallback((source, blob) => {
    counter.current += 1;
    const id = counter.current;
    const file = new File([blob], `${source}-capture-${id}.jpg`, { type: 'image/jpeg' });
    setFrames((prev) => ({
      ...prev,
      [source]: [...(prev[source] ?? []), { id, file, url: URL.createObjectURL(file) }],
    }));
  }, []);

  const remove = useCallback((source, id) => {
    const target = latest.current[source]?.find((f) => f.id === id);
    if (target) URL.revokeObjectURL(target.url);
    setFrames((prev) => ({ ...prev, [source]: (prev[source] ?? []).filter((f) => f.id !== id) }));
  }, []);

  useEffect(() => () => {
    Object.values(latest.current).flat().forEach((f) => URL.revokeObjectURL(f.url));
  }, []);

  return { frames, add, remove };
}
