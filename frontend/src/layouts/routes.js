/** Route constants and pure routing helpers (no React, so they are unit-testable with `node --test`). */

export const ALERTS_BASE = '/alerts';

/** Tabs of the merged Alerts page. Paths match what each tab shows. */
export const ALERT_TABS = [
  { id: 'vault', label: 'Vault alerts', to: `${ALERTS_BASE}/vault` },
  { id: 'all', label: 'All alerts', to: `${ALERTS_BASE}/all` },
  { id: 'branch', label: 'Branch events', to: `${ALERTS_BASE}/branch` },
];

/** Branch pages that moved out of /branch-exterior (still rendered inside BxLayout). */
export const MOVED_BRANCH_PAGES = ['/regions', '/guards', '/settings'];

/** Old URL -> new URL. Each is registered as a redirect that keeps the query string and hash. */
export const LEGACY_REDIRECTS = [
  ['/vault-alerts', `${ALERTS_BASE}/vault`],
  ['/alert-center', `${ALERTS_BASE}/all`],
  ['/branch-exterior/dashboard', `${ALERTS_BASE}/branch`],
  ['/branch-exterior/regions', '/regions'],
  ['/branch-exterior/guards', '/guards'],
  ['/branch-exterior/settings', '/settings'],
];

const trimSlash = (path) => (path.length > 1 ? path.replace(/\/+$/, '') : path);

/** Where an old URL should go (query and hash preserved), or null if the path is not a legacy URL. */
export function redirectTarget(pathname, search = '', hash = '') {
  const hit = LEGACY_REDIRECTS.find(([from]) => from === trimSlash(pathname));
  return hit ? `${hit[1]}${search}${hash}` : null;
}

const underPath = (pathname, base) => pathname === base || pathname.startsWith(`${base}/`);

/** True on pages that run inside BxLayout (shared Branch feed, theme, toasts): the header shows Branch controls. */
export function showsBranchChrome(pathname) {
  return underPath(pathname, '/branch-exterior') || underPath(pathname, `${ALERTS_BASE}/branch`)
    || MOVED_BRANCH_PAGES.some((base) => underPath(pathname, base));
}

/** Key into BX_PAGES for the sub-bar text. The Branch events tab is the old Alerts Dashboard. */
export function bxPageKey(pathname) {
  if (underPath(pathname, `${ALERTS_BASE}/branch`)) return 'dashboard';
  const moved = MOVED_BRANCH_PAGES.find((base) => underPath(pathname, base));
  if (moved) return moved.slice(1);
  return pathname.split('/')[2] || 'live';
}
