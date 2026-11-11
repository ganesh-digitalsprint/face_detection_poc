import { bxApiUrl } from './api/index.js';
import { fmApiUrl, qs } from '../face-mask/api/index.js';
import { buildCombinedCsv, trimBranchCsv } from './briefExport.js';
import {
  branchCsvParams, describeFilters, faceMaskParams, includesUseCase, resolveRange,
} from './briefFilters.js';
import { serviceById, unavailableMessage } from '../../config/serviceRegistry.js';

async function fetchCsv(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}

/** Save text as a file in the browser (no server round trip, nothing leaves the machine). */
export function saveTextFile(name, text, type = 'text/csv;charset=utf-8') {
  const href = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = href; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

const SOURCES = [
  {
    useCase: 'face_mask', label: 'Face Mask', service: 'face-mask',
    url: (filters, now) => fmApiUrl(`/reports/events.csv${qs(faceMaskParams(filters, now))}`),
  },
  {
    useCase: 'branch_exterior', label: 'Branch Exterior', service: 'branch',
    url: (filters, now) => bxApiUrl(`/events/export/csv${qs(branchCsvParams(filters, now))}`),
  },
];

/**
 * Download the filtered events as CSV.
 * One use case -> that service's own export. All -> one combined file with a `use_case` column for every reachable
 * service; the others are named in `skipped` (and in the file's header lines).
 * Resolves { fileName, skipped: [{ label, reason }], rows } - never rejects for a single down service.
 */
export async function downloadBriefCsv(filters, cameraNames = {}, now = new Date()) {
  const { until } = resolveRange(filters, now);
  const wanted = SOURCES.filter((s) => includesUseCase(filters, s.useCase));
  const skipped = [];
  if (filters.useCase === 'all' || filters.useCase === 'vault_access') {
    skipped.push({ label: 'Vault Access', reason: 'no event export is connected to this page yet' });
  }
  const parts = {};
  await Promise.all(wanted.map(async (s) => {
    try { parts[s.useCase] = await fetchCsv(s.url(filters, now)); } catch (error) {
      const down = error instanceof TypeError;
      skipped.push({ label: s.label, reason: down ? unavailableMessage(serviceById(s.service)) : `export failed (${error.message})` });
    }
  }));
  const stamp = now.toISOString().slice(0, 10);
  const reachable = Object.keys(parts);
  if (reachable.length === 0) return { fileName: null, skipped, rows: 0 };

  if (filters.useCase !== 'all') {
    const only = parts[reachable[0]];
    const text = reachable[0] === 'branch_exterior' ? trimBranchCsv(only, until) : only;
    saveTextFile(`${filters.useCase}_events_${stamp}.csv`, text);
    return { fileName: `${filters.useCase}_events_${stamp}.csv`, skipped: skipped.filter((s) => s.label !== 'Vault Access'), rows: null };
  }
  const text = buildCombinedCsv(parts, { until, skipped, filtersText: describeFilters(filters, cameraNames) });
  const fileName = `all_use_cases_events_${stamp}.csv`;
  saveTextFile(fileName, text);
  return { fileName, skipped, rows: null };
}
