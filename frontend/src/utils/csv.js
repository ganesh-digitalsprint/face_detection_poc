// Tiny RFC 4180 reader/writer used to merge the per-service CSV exports into one file.

/** Parse CSV text into rows of cells (handles quoted cells, doubled quotes and CRLF). */
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  const src = String(text ?? '').replace(/^﻿/, '');
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') { cell += '"'; i += 1; } else if (ch === '"') quoted = false; else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(cell); cell = ''; } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && src[i + 1] === '\n') i += 1;
      row.push(cell); cell = '';
      if (row.length > 1 || row[0] !== '') rows.push(row);
      row = [];
    } else cell += ch;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

/** Neutralise spreadsheet formula injection in text cells (same rule as the Face Mask exporter). */
export const safeCell = (value) => {
  const text = value == null ? '' : String(value);
  return /^[=+@\t\r]/.test(text) ? `'${text}` : text;
};

const quote = (value) => {
  const text = value == null ? '' : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

/** Rows of cells -> CSV text with CRLF line endings. */
export const toCsv = (rows) => `${rows.map((r) => r.map(quote).join(',')).join('\r\n')}\r\n`;

/** Header row + data rows -> array of objects keyed by header. */
export function rowsToObjects(rows) {
  const [header = [], ...body] = rows;
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}
