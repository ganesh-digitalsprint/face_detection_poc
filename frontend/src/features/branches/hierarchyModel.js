export function hierarchySearch(kind, id, { zoneId = '', cityId = '' } = {}) {
  const next = new URLSearchParams();
  if (!id && kind === 'zone') next.set('all', '1');
  if (kind === 'zone' && id) next.set('zone', id);
  if (kind === 'city' || kind === 'branch') {
    if (zoneId) next.set('zone', zoneId);
    if (id || kind === 'branch') next.set('city', kind === 'city' ? id : cityId);
  }
  if (kind === 'branch' && id) next.set('branch', id);
  return next;
}

// Keeps slow responses from a previous hierarchy selection out of the current view.
export function createLatestLoader() {
  let revision = 0;
  return {
    invalidate() { revision += 1; },
    async run(load, { success, failure, settled } = {}) {
      const request = ++revision;
      try {
        const value = await load();
        if (request === revision) success?.(value);
        return value;
      } catch (error) {
        if (request === revision) failure?.(error);
        return undefined;
      } finally {
        if (request === revision) settled?.();
      }
    },
  };
}

export function cameraState({ loading, cameras }) {
  if (loading) return 'loading';
  return cameras.length ? 'ready' : 'empty';
}
