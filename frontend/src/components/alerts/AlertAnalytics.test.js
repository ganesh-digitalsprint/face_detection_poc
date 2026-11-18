import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('analytics panels render loading, error, no-data, and real summary shapes', async () => {
  const server = await createServer({ root: process.cwd(), server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
  try {
    const { default: AlertAnalytics } = await server.ssrLoadModule('/src/components/alerts/AlertAnalytics.jsx');
    const render = (props) => renderToStaticMarkup(createElement(AlertAnalytics, props));

    assert.match(render({ loading: true }), /Loading analytics/);
    assert.match(render({ error: new Error('unavailable') }), /Analytics are unavailable/);
    const empty = render({ summary: { total: 0, by_day: [], by_status: { OPEN: 0 }, by_severity: { HIGH: 0 }, by_use_case: [], by_branch: [] } });
    assert.match(empty, /Alerts over time/);
    assert.match(empty, /No alerts match the selected filters/);
    const failed = render({ error: new Error('offline'), errorMessage: 'Alert Service is unavailable.', onRetry: () => {} });
    assert.match(failed, /Alert Service is unavailable/);
    assert.match(failed, /Retry analytics/);

    const populated = render({ summary: {
      total: 4,
      by_day: [{ date: '2026-11-01', count: 4 }],
      by_status: { OPEN: 2, ACKNOWLEDGED: 1, RESOLVED: 1, DISMISSED: 0 },
      by_severity: { INFO: 0, WARNING: 1, HIGH: 2, CRITICAL: 1 },
      by_use_case: [{ use_case: 'grill_gate', count: 3 }, { use_case: 'vault_monitoring', count: 1 }],
      by_branch: [{ branch_id: 'branch-1', branch_name: 'Central', branch_code: 'C001', count: 3 },
        { branch_id: null, branch_name: 'Unassigned', branch_code: null, count: 1 }],
    } });
    for (const title of ['Alerts over time', 'Severity mix', 'Alerts by source', 'When alerts happen']) {
      assert.match(populated, new RegExp(title));
    }
    assert.doesNotMatch(populated, /Alerts by status|Alerts by branch/);
    assert.match(populated, /Hourly aggregation unavailable/);
    assert.match(populated, /4 alerts/);
  } finally {
    await server.close();
  }
});
