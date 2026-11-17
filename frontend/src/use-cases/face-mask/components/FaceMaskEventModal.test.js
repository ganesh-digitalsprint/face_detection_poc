import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
test('Face Mask event details reuse the accessible wide Branch Exterior modal', async () => {
  const modalSource = await readFile(new URL('./FaceMaskEventModal.jsx', import.meta.url), 'utf8');
  assert.match(modalSource, /import Modal from '\.\.\/\.\.\/branch-exterior\/components\/Modal\.jsx'/);
  assert.match(modalSource, /maxWidth="min\(90vw, 1120px\)"/);
  assert.match(modalSource, /Close details/);
  assert.match(modalSource, /\['Source event ID', event\.id\], \['Incident ID', incidentLocation \? incidentId : 'Not yet available in Alert Center'\]/);
  assert.match(modalSource, /faceMaskIncidentLocation\(incidentId\)/);
  assert.match(modalSource, /View in Alert Center/);
  assert.match(modalSource, /Open Alert Center/);
  assert.match(modalSource, /incidentLookupError/);
  assert.match(modalSource, /api\.get\(`\/events\/\$\{encodeURIComponent\(eventId\)\}`\)/);
});

test('concealment cards open the stable source event and show an evidence placeholder when missing', async () => {
  const cardSource = await readFile(new URL('./FaceMaskConcealmentCard.jsx', import.meta.url), 'utf8');
  assert.match(cardSource, /onClick=\{\(\) => onSelect\(event\.id\)\}/);
  assert.match(cardSource, /Masked person detected/);
  assert.match(cardSource, /Snapshot unavailable/);
  assert.match(cardSource, /onError=\{\(\) => setImageFailed\(true\)\}/);
});

test('the shared evidence layout preserves aspect ratio and adapts its details grid on small screens', async () => {
  const css = await readFile(new URL('../../branch-exterior/branchExterior.css', import.meta.url), 'utf8');
  assert.match(css, /\.bx-detail-media img, \.bx-detail-media video[^}]*object-fit: contain/s);
  assert.match(css, /@media \(max-width: 620px\)[\s\S]*?\.bx-event-details \{ grid-template-columns: minmax\(0, 1fr\);/);
});
