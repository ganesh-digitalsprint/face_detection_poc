import {
  Activity, Bell, DoorClosed, EyeOff, FileText, Film, LayoutDashboard, LockKeyhole, Map as MapIcon,
  Radio, ScanFace, Settings as SettingsIcon, ShieldCheck, Users, Video, Webcam, Cctv,
} from 'lucide-react';

/**
 * Single source of truth for the sidebar.
 *
 * section = { label?, muted?, items: item[] }
 * item    = { id, label, icon?, to?, end?, match?, badge?, dev?, soon?, defaultOpen?, children? }
 *
 * - `to` makes the item a link; an item with `children` is a collapsible group (a button, never a link).
 * - `match` lists extra path prefixes that also mark the item active (e.g. nested registration routes).
 * - `badge` is a slot key; the live count is passed to <Sidebar> as `badges[key]`.
 * - `dev` items are shown only when the dev menu flag is on.
 * - `soon` items are disabled placeholders.
 *
 * Adding a use case = one new group in the USE CASES section.
 */
export const NAV_SECTIONS = [
  {
    items: [{ id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, to: '/', end: true }],
  },
  {
    label: 'Operations',
    items: [
      {
        id: 'alerts',
        label: 'Alerts',
        icon: Bell,
        to: '/alerts',
        match: ['/vault-alerts'], // incident detail still lives at /vault-alerts/incidents/:id
        badge: 'alerts',
      },
      { id: 'brief', label: 'Security Brief', icon: FileText, to: '/branch-exterior/brief' },
    ],
  },
  {
    label: 'Use cases',
    items: [
      {
        id: 'vault-access',
        label: 'Vault Access',
        icon: LockKeyhole,
        defaultOpen: true,
        children: [{ id: 'vault-door', label: 'Door authorization', to: '/vault-access' }],
      },
      {
        id: 'branch-exterior',
        label: 'Branch Exterior',
        icon: Video,
        children: [{ id: 'branch-live', label: 'Live monitoring', to: '/branch-exterior/live' }],
      },
      { id: 'gate-mesh', label: 'Gate & Mesh', icon: DoorClosed, soon: true },
      { id: 'face-concealment', label: 'Face Concealment', icon: EyeOff, soon: true },
    ],
  },
  {
    label: 'Configuration',
    items: [
      { id: 'employees', label: 'Employees', icon: Users, to: '/registration/employees', match: ['/registration/authorized'] },
      { id: 'regions', label: 'Regions & Zones', icon: MapIcon, to: '/regions' },
      { id: 'guards', label: 'Guard Roster', icon: ShieldCheck, to: '/guards' },
      { id: 'settings', label: 'Settings', icon: SettingsIcon, to: '/settings' },
      { id: 'system-check', label: 'System Check', icon: Activity, to: '/branch-exterior/system-check' },
    ],
  },
  {
    label: 'Tools',
    muted: true,
    items: [
      { id: 'liveness', label: 'Liveness Test', icon: ScanFace, to: '/liveness-test', dev: true },
      {
        id: 'live',
        label: 'Live Monitoring',
        icon: Radio,
        children: [
          { id: 'live-overview', label: 'Overview', to: '/live', end: true },
          { id: 'live-webcam', label: 'Webcam', icon: Webcam, to: '/live/webcam' },
          { id: 'live-cctv', label: 'CCTV', icon: Cctv, to: '/live/cctv' },
        ],
      },
      { id: 'video', label: 'Video Recognition', icon: Film, to: '/video' },
    ],
  },
];

const trimSlash = (path) => (path.length > 1 ? path.replace(/\/+$/, '') : path);

/** Same matching rule as React Router's NavLink: exact when `end`, otherwise the path or any descendant. */
export function pathMatches(target, pathname, end = false) {
  const t = trimSlash(target);
  const p = trimSlash(pathname);
  if (t === '/') return end ? p === '/' : true;
  return p === t || (!end && p.startsWith(`${t}/`));
}

/** True when the item (or, for a group, any child) owns the current path. */
export function isItemActive(item, pathname) {
  if (item.soon) return false;
  if (item.children?.some((child) => isItemActive(child, pathname))) return true;
  if (item.to && pathMatches(item.to, pathname, item.end)) return true;
  return (item.match ?? []).some((prefix) => pathMatches(prefix, pathname));
}

/** Drops `dev` items unless the dev menu is enabled, and sections left with nothing to show. */
export function visibleSections(sections, { devEnabled = false } = {}) {
  return sections
    .map((section) => ({ ...section, items: section.items.filter((item) => devEnabled || !item.dev) }))
    .filter((section) => section.items.length > 0);
}

/** Ids of groups that should be open: flagged `defaultOpen`, or holding the active route. */
export function openGroupIds(sections, pathname) {
  return sections
    .flatMap((section) => section.items)
    .filter((item) => item.children && (item.defaultOpen || isItemActive(item, pathname)))
    .map((item) => item.id);
}

/** Every link target in the config (soon/placeholder items have none). */
export function linkTargets(sections) {
  return sections
    .flatMap((section) => section.items)
    .flatMap((item) => (item.children ? item.children : [item]))
    .filter((item) => item.to && !item.soon)
    .map((item) => item.to);
}

/** Alerts badge text: hidden at 0 or when unknown, "99+" above 99. */
export function formatBadge(count) {
  if (!Number.isFinite(count) || count <= 0) return null;
  return count > 99 ? '99+' : String(count);
}
