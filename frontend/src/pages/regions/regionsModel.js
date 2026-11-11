/** Pure helpers for the common Regions & Zones page (no React, so they are unit-testable with `node --test`). */

export const USE_CASES = [
  { id: 'all', label: 'All' },
  { id: 'vault_access', label: 'Vault Access' },
  { id: 'branch_exterior', label: 'Branch Exterior' },
  { id: 'face_mask', label: 'Face Mask' },
];

/** Zone types each use case supports. Vault Access has no drawable zones yet. */
export const ZONE_TYPES = {
  vault_access: [],
  branch_exterior: ['entrance', 'atm', 'side_lane', 'forecourt', 'rear', 'restricted', 'other'],
  face_mask: ['entry_roi'],
};

export const ZONE_TYPE_LABELS = {
  entrance: 'Entrance / gate', atm: 'ATM area', side_lane: 'Side lane', forecourt: 'Forecourt / parking',
  rear: 'Rear access', restricted: 'Restricted', other: 'Other', entry_roi: 'Entry ROI',
};

export const SERVICE_START = {
  branch_exterior: { name: 'Branch Exterior', dir: 'backend/use_cases/branch_exterior', cmd: 'python -m uvicorn app.main:app --port 8011' },
  face_mask: { name: 'Face Mask', dir: 'backend/use_cases/face_mask', cmd: 'uv run uvicorn app.main:app --reload --port 8014' },
};

/** Valid use-case id from a query-string value; anything unknown falls back to "all". */
export function parseUseCase(value) {
  return USE_CASES.some((u) => u.id === value) ? value : 'all';
}

/** Normalise a Branch zone to the common zone shape. Branch zones have no enabled flag: always on. */
export function fromBranchZone(zone) {
  return {
    id: zone.id, use_case: 'branch_exterior', camera_id: zone.camera_id, name: zone.name,
    zone_type: zone.zone_type, points: (zone.polygon || []).length, enabled: true, direction: false,
  };
}

/** Normalise a Face Mask entry ROI to the common zone shape. */
export function fromFaceMaskRoi(roi) {
  return {
    id: roi.id, use_case: 'face_mask', camera_id: roi.camera_id, name: roi.name,
    zone_type: roi.zone_type || 'entry_roi', points: (roi.polygon || []).length,
    enabled: roi.enabled !== false, direction: Boolean(roi.inward_vector),
  };
}

/** Rows for the "All" table, filtered by use case. */
export function filterZones(zones, useCase) {
  return useCase === 'all' ? zones : zones.filter((z) => z.use_case === useCase);
}
