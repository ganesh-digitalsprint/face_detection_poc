export function isRegionsDraftDirty({
  drawing = false,
  drawPoints = [],
  editingZoneId = null,
  editOriginal = null,
  redrawMode = false,
  zoneFormDirty = false,
} = {}) {
  if (zoneFormDirty) return true;
  if (!drawing) return false;
  if (!editingZoneId) return drawPoints.length > 0;
  if (redrawMode) return true;
  if (!editOriginal) return drawPoints.length > 0;
  return JSON.stringify(drawPoints) !== JSON.stringify(editOriginal);
}

export function cloneZoneSnapshot(zones = []) {
  return JSON.parse(JSON.stringify(zones));
}
