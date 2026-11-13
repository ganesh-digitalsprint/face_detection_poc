import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  NAV_SECTIONS, formatBadge, isItemActive, linkTargets, navigationTarget, openGroupIds, pathMatches, visibleSections,
} from './navConfig.js';

const allItems = NAV_SECTIONS.flatMap((s) => s.items).flatMap((i) => [i, ...(i.children ?? [])]);
const byId = (id) => allItems.find((i) => i.id === id);

test('ids are unique', () => {
  const ids = allItems.map((i) => i.id);
  assert.equal(new Set(ids).size, ids.length);
});

test('every item is a link, a group of links, or a disabled "soon" placeholder', () => {
  for (const item of allItems) {
    if (item.soon) assert.ok(!item.to && !item.children, `${item.id}: soon items are not links`);
    else if (item.children) assert.ok(!item.to && item.children.every((c) => c.to), `${item.id}: group children are links`);
    else assert.match(item.to, /^\//, `${item.id}: link target`);
  }
});

test('every pre-redesign menu URL is still reachable', () => {
  const targets = linkTargets(NAV_SECTIONS).map((target) => target.split('?')[0]);
  for (const url of [
    '/', '/registration/employees', '/vault-access', '/alerts',
    '/branch-exterior/live', '/regions', '/branch-exterior/brief',
    '/guards', '/settings', '/branch-exterior/system-check',
    '/liveness-test', '/live', '/live/webcam', '/live/cctv', '/video',
  ]) assert.ok(targets.includes(url), url);
});

test('pathMatches follows NavLink rules', () => {
  assert.ok(pathMatches('/live', '/live/webcam'));
  assert.ok(!pathMatches('/live', '/live/webcam', true));
  assert.ok(pathMatches('/live', '/live/', true));
  assert.ok(!pathMatches('/live', '/livestock'));
  assert.ok(pathMatches('/', '/', true));
  assert.ok(!pathMatches('/', '/video', true));
});

test('active route marks its item and owning group; Dashboard only matches "/"', () => {
  assert.ok(isItemActive(byId('alerts'), '/alerts/all'));
  assert.ok(isItemActive(byId('alerts'), '/alerts/branch'));
  assert.ok(isItemActive(byId('alerts'), '/vault-alerts/incidents/42'));
  assert.ok(!isItemActive(byId('alerts'), '/alerts-archive'));
  assert.ok(isItemActive(byId('dashboard'), '/'));
  assert.ok(!isItemActive(byId('dashboard'), '/video'));
  assert.ok(!isItemActive(byId('live-overview'), '/live/webcam'));
  assert.ok(isItemActive(byId('live'), '/live/webcam'));
});

test('Employees is also active on nested authorized-registration routes', () => {
  assert.ok(isItemActive(byId('employees'), '/registration/employees'));
  assert.ok(isItemActive(byId('employees'), '/registration/authorized/7/face'));
  assert.ok(!isItemActive(byId('employees'), '/registration'));
});

test('soon items are never active', () => {
  assert.ok(!isItemActive({ id: 'placeholder', soon: true }, '/'));
  assert.equal(byId('face-concealment'), undefined);
  assert.ok(!linkTargets(NAV_SECTIONS).some((t) => t.includes('concealment')));
});

test('Gate & Mesh links to the Grill Gate page', () => {
  assert.deepEqual(byId('gate-mesh').children.map((child) => child.to), ['/grill-gate', '/grill-gate?view=video', '/grill-gate?view=zones']);
  assert.ok(isItemActive(byId('gate-mesh'), '/grill-gate'));
});

test('groups open by default flag or when a child route is active', () => {
  assert.deepEqual(openGroupIds(NAV_SECTIONS, '/video'), []);
  assert.deepEqual(openGroupIds(NAV_SECTIONS, '/alerts/all'), []);
  assert.ok(openGroupIds(NAV_SECTIONS, '/branch-exterior/live').includes('branch-exterior'));
  assert.ok(openGroupIds(NAV_SECTIONS, '/live/cctv').includes('live'));
});

test('Vault Monitoring reuses query-based submenus and has exactly one active child', () => {
  const group = byId('vault-access');
  assert.equal(group.label, 'Vault Monitoring');
  assert.deepEqual(group.children.map((child) => child.label), ['Entrance Camera', 'Vault Room Camera', 'Zones & Regions']);
  for (const view of ['entrance', 'room', 'zones']) {
    const search = `?view=${view}&source=upload`;
    assert.equal(group.children.filter((child) => isItemActive(child, '/vault-access', search)).length, 1);
    assert.ok(isItemActive(byId(`vault-${view}`), '/vault-access', search));
    assert.ok(openGroupIds(NAV_SECTIONS, '/vault-access', search).includes('vault-access'));
  }
});

test('legacy Vault URL follows saved view, and submenu navigation preserves query state', () => {
  const previous = globalThis.localStorage;
  try {
    globalThis.localStorage = { getItem: () => JSON.stringify({ view: 'room', source: 'upload' }) };
    assert.ok(isItemActive(byId('vault-room'), '/vault-access'));
    assert.ok(!isItemActive(byId('vault-entrance'), '/vault-access'));
    assert.ok(isItemActive(byId('vault-entrance'), '/vault-access', '?view=entrance'));
    const target = navigationTarget(byId('vault-zones'), '/vault-access', '?view=room&source=upload&camera=42');
    const params = new URLSearchParams(target.split('?')[1]);
    assert.equal(params.get('view'), 'zones'); assert.equal(params.get('source'), 'upload'); assert.equal(params.get('camera'), '42');
    assert.equal(navigationTarget(byId('vault-room'), '/alerts', '?scope=history'), '/vault-access?view=room');
    assert.equal(navigationTarget(byId('gate-mesh-video'), '/grill-gate', '?unrelated=1'), '/grill-gate?view=video');
  } finally { if (previous === undefined) delete globalThis.localStorage; else globalThis.localStorage = previous; }
});

test('Liveness Test appears only when the dev flag is on', () => {
  const ids = (opts) => visibleSections(NAV_SECTIONS, opts).flatMap((s) => s.items).map((i) => i.id);
  assert.ok(!ids({ devEnabled: false }).includes('liveness'));
  assert.ok(!ids().includes('liveness'));
  assert.ok(ids({ devEnabled: true }).includes('liveness'));
});

test('formatBadge hides 0/unknown and caps above 99', () => {
  for (const v of [0, -1, undefined, null, NaN]) assert.equal(formatBadge(v), null);
  assert.equal(formatBadge(7), '7');
  assert.equal(formatBadge(99), '99');
  assert.equal(formatBadge(100), '99+');
});
