import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { ALERTS_BASE, LEGACY_REDIRECTS, MOVED_BRANCH_PAGES, bxPageKey, redirectTarget, showsBranchChrome } from './routes.js';
import { linkTargets, NAV_SECTIONS } from './navConfig.js';

test('legacy alert URLs redirect to the centralized Alert Center', () => {
  assert.equal(redirectTarget('/vault-alerts'), '/alerts?use_case=vault_monitoring');
  assert.equal(redirectTarget('/alert-center'), '/alerts');
  assert.equal(redirectTarget('/branch-exterior/dashboard'), '/alerts?use_case=branch_exterior');
  assert.equal(redirectTarget('/alerts/face-mask'), '/alerts?use_case=face_mask');
});

test('redirects keep the query string and hash, and tolerate a trailing slash', () => {
  assert.equal(redirectTarget('/vault-alerts', '?scope=history'), '/alerts?scope=history&use_case=vault_monitoring');
  assert.equal(redirectTarget('/alert-center/', '?status=OPEN'), '/alerts?status=OPEN');
  assert.equal(redirectTarget('/branch-exterior/dashboard', '?event=42', '#x'), '/alerts?use_case=branch_exterior&source_event_id=42#x');
});

test('non-legacy URLs are not redirected (incident detail and Branch pages keep their URLs)', () => {
  for (const p of ['/vault-alerts/incidents/7', '/alerts', '/branch-exterior/live', '/settings', '/']) {
    assert.equal(redirectTarget(p, '?a=1'), null, p);
  }
});

test('moved Branch pages redirect from /branch-exterior and keep ?camera= and other params', () => {
  assert.equal(redirectTarget('/branch-exterior/regions', '?camera=3'), '/regions?camera=3');
  assert.equal(redirectTarget('/branch-exterior/guards'), '/guards');
  assert.equal(redirectTarget('/branch-exterior/settings', '?tab=policies'), '/settings?tab=policies');
  for (const p of ['/regions', '/guards', '/settings', '/branch-exterior/system-check', '/branch-exterior/live', '/branch-exterior/brief']) {
    assert.equal(redirectTarget(p), null, p);
  }
});

test('every alert redirect lands on the one Alert Center route', () => {
  for (const [, to] of LEGACY_REDIRECTS) assert.ok(to === ALERTS_BASE || MOVED_BRANCH_PAGES.includes(to) || to === '/regions', to);
  const sources = LEGACY_REDIRECTS.map(([from]) => from);
  assert.equal(new Set(sources).size, sources.length);
  for (const [, to] of LEGACY_REDIRECTS) assert.ok(!sources.includes(to), `redirect loop: ${to}`);
});

test('Branch header controls show only where BxLayout is mounted', () => {
  for (const p of ['/branch-exterior/live', '/branch-exterior', '/guards', '/settings']) assert.ok(showsBranchChrome(p), p);
  // /regions is the common Regions & Zones page: it is not rendered inside BxLayout.
  for (const p of ['/regions', '/alerts', '/branch-exteriors', '/regionsx', '/vault-access', '/registration/employees']) {
    assert.ok(!showsBranchChrome(p), p);
  }
});

test('BxLayout sub-bar key follows Branch monitoring routes', () => {
  assert.equal(bxPageKey('/guards'), 'guards');
  assert.equal(bxPageKey('/settings'), 'settings');
  assert.equal(bxPageKey('/branch-exterior/system-check'), 'system-check');
  assert.equal(bxPageKey('/branch-exterior'), 'live');
});

test('sidebar links every tab through one Alerts entry and no longer lists old alert URLs', () => {
  const targets = linkTargets(NAV_SECTIONS);
  assert.ok(targets.includes('/alerts'));
  for (const [from] of LEGACY_REDIRECTS) assert.ok(!targets.includes(from), from);
});

test('App registers a redirect for every legacy URL and no page still renders at one', () => {
  const app = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8');
  assert.match(app, /LEGACY_REDIRECTS\.map/);
  assert.ok(!/path="(alert-center|vault-alerts|dashboard)"/.test(app));
  for (const page of ['regions', 'guards', 'settings']) {
    assert.equal((app.match(new RegExp(`path="${page}"`, 'g')) ?? []).length, 1, `${page} registered once`);
  }
});

test('Settings tabs: unknown or missing ?tab= falls back to General', async () => {
  const { SETTINGS_TABS, resolveSettingsTab } = await import('../use-cases/branch-exterior/settingsTabs.js');
  assert.deepEqual(SETTINGS_TABS.map((t) => t.id), ['general', 'policies', 'integrations', 'face-mask']);
  assert.equal(resolveSettingsTab('policies'), 'policies');
  for (const v of [null, undefined, '', 'users', '__proto__']) assert.equal(resolveSettingsTab(v), 'general');
});
