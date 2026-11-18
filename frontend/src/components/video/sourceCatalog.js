const videoTypes = new Set(['folder', 'upload', 'video_file']);

export const sourceKey = (file) => file.upload_id ? `upload:${file.upload_id}` : `${file.category === 'sample_videos' ? 'sample' : 'file'}:${file.path}`;
export const savedSourceKey = (storage, useCase) => {
  try { return storage.getItem(`liveSource:${useCase}`) || ''; } catch { return ''; }
};
export const rememberSourceKey = (storage, useCase, key) => {
  try { if (key) storage.setItem(`liveSource:${useCase}`, key); else storage.removeItem(`liveSource:${useCase}`); } catch { /* storage unavailable */ }
};

const comparable = (value) => String(value || '').replaceAll('\\', '/').toLowerCase();

export function sourceCatalog({ files = [], browse = [], cameras = [], statuses = {}, preferredCameraId = '' }) {
  const videos = [];
  const usedCameras = new Set();
  const usedFiles = new Set();
  for (const file of files) {
    if (!['sample_videos', 'uploads'].includes(file.category) || (file.upload_status && file.upload_status !== 'uploaded')) continue;
    const key = sourceKey(file);
    if (usedFiles.has(key)) continue;
    usedFiles.add(key);
    const candidate = browse.find((entry) => comparable(entry.path) === comparable(key)
      || comparable(entry.path) === comparable(file.path)
      || comparable(entry.path).endsWith(`/${comparable(file.path)}`));
    const matches = cameras.filter((entry) => videoTypes.has(entry.cam_type)
      && (comparable(entry.source) === comparable(key) || comparable(entry.source) === comparable(candidate?.path)
        || comparable(entry.source) === comparable(file.path)
        || comparable(entry.source).endsWith(`/${comparable(file.path)}`)));
    matches.forEach((entry) => usedCameras.add(entry.id));
    const camera = matches.find((entry) => statuses[entry.id]?.running || entry.stream?.running)
      || matches.find((entry) => entry.id === preferredCameraId) || matches[0];
    videos.push({ ...file, id: key, kind: 'video', cameraId: camera?.id || null,
      processPath: candidate?.path || (file.upload_id ? key : file.path),
      status: camera ? statuses[camera.id]?.status || (statuses[camera.id]?.running ? 'PROCESSING' : '') || camera.stream?.status || 'STOPPED' : '' });
  }
  const unmatchedSources = new Set();
  for (const camera of cameras) {
    if (usedCameras.has(camera.id)) continue;
    if (videoTypes.has(camera.cam_type)) {
      const source = comparable(camera.source);
      if (unmatchedSources.has(source)) continue;
      unmatchedSources.add(source);
      const key = `camera:${camera.id}`;
      videos.push({ id: key, kind: 'video', name: camera.name, cameraId: camera.id,
        processPath: camera.source, status: statuses[camera.id]?.status || (statuses[camera.id]?.running ? 'PROCESSING' : '') || camera.stream?.status || 'STOPPED' });
    }
  }
  const live = cameras.filter((camera) => !videoTypes.has(camera.cam_type)).map((camera) => ({
    id: `camera:${camera.id}`, kind: 'camera', name: camera.name, cameraId: camera.id,
    code: camera.code, width: camera.width, height: camera.height, codec: camera.codec,
    status: statuses[camera.id]?.status || (statuses[camera.id]?.running ? 'PROCESSING' : '') || camera.stream?.status || 'STOPPED',
  }));
  const uploads = videos.filter((item) => item.category === 'uploads');
  uploads.sort((a, b) => (Date.parse(b.created_at || '') || b.modified * 1000 || 0) - (Date.parse(a.created_at || '') || a.modified * 1000 || 0));
  return { cameras: live, uploads,
    samples: videos.filter((item) => item.category !== 'uploads') };
}

export const flattenSources = (groups) => [...groups.cameras, ...groups.uploads, ...groups.samples];
export const filterSources = (groups, query) => {
  const term = query.trim().toLowerCase();
  return Object.fromEntries(Object.entries(groups).map(([key, items]) => [key, items.filter((item) => item.name.toLowerCase().includes(term))]));
};
