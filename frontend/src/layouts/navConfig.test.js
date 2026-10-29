import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  NAV_SECTIONS, formatBadge, isItemActive, linkTargets, openGroupIds, pathMatches, visibleSections,
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
  const targets = linkTargets(NAV_SECTIONS);
  for (const url of [
    '/', '/registration/employees', '/vault-access', '/alerts',
    '/branch-exterior/live', '/branch-exterior/regions', '/branch-exterior/brief',
    '/branch-exterior/guards', '/branch-exterior/settings', '/branch-exterior/system-check',
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
  assert.ok(!isItemActive(byId('gate-mesh'), '/'));
  assert.ok(!linkTargets(NAV_SECTIONS).some((t) => t.includes('gate') || t.includes('concealment')));
});

test('groups open by default flag or when a child route is active', () => {
  assert.deepEqual(openGroupIds(NAV_SECTIONS, '/video'), ['vault-access']);
  assert.deepEqual(openGroupIds(NAV_SECTIONS, '/alerts/all'), ['vault-access']);
  assert.ok(openGroupIds(NAV_SECTIONS, '/branch-exterior/live').includes('branch-exterior'));
  assert.ok(openGroupIds(NAV_SECTIONS, '/live/cctv').includes('live'));
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
