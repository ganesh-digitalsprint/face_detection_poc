/** Route constants and pure routing helpers (no React, so they are unit-testable with `node --test`). */

export const ALERTS_BASE = '/alerts';

/** Deep link to one Face Mask event inside the Alerts page (opens the detail panel). */
export const faceMaskEventLink = (eventId) => `${ALERTS_BASE}?source_event_id=${encodeURIComponent(eventId)}`;

/** Branch pages that moved out of /branch-exterior (still rendered inside BxLayout). */
export const MOVED_BRANCH_PAGES = ['/guards', '/settings'];

/** Old URL -> new URL. Each is registered as a redirect that keeps the query string and hash. */
export const LEGACY_REDIRECTS = [
  ['/vault-alerts', ALERTS_BASE],
  ['/alert-center', ALERTS_BASE],
  ['/branch-exterior/dashboard', ALERTS_BASE],
  [`${ALERTS_BASE}/vault`, ALERTS_BASE],
  [`${ALERTS_BASE}/all`, ALERTS_BASE],
  [`${ALERTS_BASE}/branch`, ALERTS_BASE],
  [`${ALERTS_BASE}/face-mask`, ALERTS_BASE],
  ['/branch-exterior/regions', '/regions'],
  ['/branch-exterior/guards', '/guards'],
  ['/branch-exterior/settings', '/settings'],
];

const trimSlash = (path) => (path.length > 1 ? path.replace(/\/+$/, '') : path);

/** Where an old URL should go (query and hash preserved), or null if the path is not a legacy URL. */
export function redirectTarget(pathname, search = '', hash = '') {
  const hit = LEGACY_REDIRECTS.find(([from]) => from === trimSlash(pathname));
  if (!hit) return null;
  if (hit[1] !== ALERTS_BASE) return `${hit[1]}${search}${hash}`;
  const sourceByPath = {
    '/vault-alerts': 'vault_monitoring', [`${ALERTS_BASE}/vault`]: 'vault_monitoring',
    '/branch-exterior/dashboard': 'branch_exterior', [`${ALERTS_BASE}/branch`]: 'branch_exterior',
    [`${ALERTS_BASE}/face-mask`]: 'face_mask',
  };
  const params = new URLSearchParams(search);
  const source = sourceByPath[trimSlash(pathname)];
  if (source && !params.has('use_case')) params.set('use_case', source);
  if (params.has('event') && !params.has('source_event_id')) {
    params.set('source_event_id', params.get('event'));
    params.delete('event');
  }
  const nextSearch = params.size ? `?${params}` : '';
  return `${ALERTS_BASE}${nextSearch}${hash}`;
}

const underPath = (pathname, base) => pathname === base || pathname.startsWith(`${base}/`);

/** True on pages that run inside BxLayout (shared Branch feed, theme, toasts): the header shows Branch controls. */
export function showsBranchChrome(pathname) {
  return underPath(pathname, '/branch-exterior') || MOVED_BRANCH_PAGES.some((base) => underPath(pathname, base));
}

/** Key into BX_PAGES for the sub-bar text. The Branch events tab is the old Alerts Dashboard. */
export function bxPageKey(pathname) {
  const moved = MOVED_BRANCH_PAGES.find((base) => underPath(pathname, base));
  if (moved) return moved.slice(1);
  return pathname.split('/')[2] || 'live';
}
