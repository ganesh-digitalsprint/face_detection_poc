import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { ALERT_TABS, LEGACY_REDIRECTS, bxPageKey, redirectTarget, showsBranchChrome } from './routes.js';
import { linkTargets, NAV_SECTIONS } from './navConfig.js';

test('legacy alert URLs redirect to their tab', () => {
  assert.equal(redirectTarget('/vault-alerts'), '/alerts/vault');
  assert.equal(redirectTarget('/alert-center'), '/alerts/all');
  assert.equal(redirectTarget('/branch-exterior/dashboard'), '/alerts/branch');
});

test('redirects keep the query string and hash, and tolerate a trailing slash', () => {
  assert.equal(redirectTarget('/vault-alerts', '?scope=history'), '/alerts/vault?scope=history');
  assert.equal(redirectTarget('/alert-center/', '?status=OPEN'), '/alerts/all?status=OPEN');
  assert.equal(redirectTarget('/branch-exterior/dashboard', '?event=42', '#x'), '/alerts/branch?event=42#x');
});

test('non-legacy URLs are not redirected (incident detail and Branch pages keep their URLs)', () => {
  for (const p of ['/vault-alerts/incidents/7', '/alerts/vault', '/branch-exterior/live', '/branch-exterior/settings', '/']) {
    assert.equal(redirectTarget(p, '?a=1'), null, p);
  }
});

test('every redirect lands on a tab, and every tab is a distinct /alerts path', () => {
  const tabs = ALERT_TABS.map((t) => t.to);
  assert.equal(new Set(tabs).size, tabs.length);
  for (const [, to] of LEGACY_REDIRECTS) assert.ok(tabs.includes(to), to);
});

test('Branch header controls show only where BxLayout is mounted', () => {
  for (const p of ['/branch-exterior/live', '/branch-exterior', '/alerts/branch', '/alerts/branch/']) assert.ok(showsBranchChrome(p), p);
  for (const p of ['/alerts/vault', '/alerts/all', '/alerts', '/branch-exteriors', '/vault-access', '/registration/employees']) {
    assert.ok(!showsBranchChrome(p), p);
  }
});

test('BxLayout sub-bar key: Branch events tab is the old dashboard; Branch pages keep their segment', () => {
  assert.equal(bxPageKey('/alerts/branch'), 'dashboard');
  assert.equal(bxPageKey('/branch-exterior/guards'), 'guards');
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
});

test('Settings tabs: unknown or missing ?tab= falls back to General', async () => {
  const { SETTINGS_TABS, resolveSettingsTab } = await import('../use-cases/branch-exterior/settingsTabs.js');
  assert.deepEqual(SETTINGS_TABS.map((t) => t.id), ['general', 'policies', 'integrations']);
  assert.equal(resolveSettingsTab('policies'), 'policies');
  for (const v of [null, undefined, '', 'users', '__proto__']) assert.equal(resolveSettingsTab(v), 'general');
});
