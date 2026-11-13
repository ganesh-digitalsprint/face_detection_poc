import { PLATFORM_BASE_URL } from '../../config/services.js';
import { platformApi } from '../branches/api.js';

export const CHUNK_SIZE = 8 * 1024 * 1024;
export const MAX_SIZE = 2 * 1024 ** 3;
const allowed = new Set(['mp4', 'avi', 'mov', 'mkv']);

export function validateVideo(file) {
  if (!file || !allowed.has(file.name.split('.').at(-1).toLowerCase())) throw new Error('Use MP4, AVI, MOV or MKV.');
  if (!file.size || file.size > MAX_SIZE) throw new Error('Video must be between 1 byte and 2 GB.');
}

function sendChunk(id, blob, offset, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('PATCH', `${PLATFORM_BASE_URL}/uploads/${encodeURIComponent(id)}`);
    request.setRequestHeader('Upload-Offset', String(offset));
    request.upload.onprogress = (event) => onProgress(offset + event.loaded);
    request.onload = () => request.status === 200 ? resolve(JSON.parse(request.responseText)) : reject(new Error(`Chunk failed (${request.status})`));
    request.onerror = () => reject(new Error('Network error while uploading.'));
    request.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'));
    const abort = () => request.abort();
    signal.addEventListener('abort', abort, { once: true });
    request.onloadend = () => signal.removeEventListener('abort', abort);
    if (signal.aborted) abort(); else request.send(blob);
  });
}

export async function uploadVideo(file, { branchId, cameraId, useCase, onProgress, signal, previousId }) {
  validateVideo(file);
  let id = previousId;
  try {
    let offset = 0;
    if (id) {
      const previous = await platformApi(`/uploads/${encodeURIComponent(id)}`);
      if (previous.status === 'failed') return platformApi(`/uploads/${encodeURIComponent(id)}/retry`, { method: 'POST' });
      if (previous.status !== 'uploading') throw new Error(`Cannot resume a ${previous.status} upload`);
      offset = previous.received;
    } else {
      const created = await platformApi('/uploads', { method: 'POST', body: JSON.stringify({ branch_id: branchId, camera_id: cameraId || null, use_case: useCase || null, name: file.name, size: file.size }) });
      id = created.id;
    }
    onProgress(offset, id);
    while (offset < file.size) {
      if (signal.aborted) throw new DOMException('Upload cancelled', 'AbortError');
      const end = Math.min(offset + CHUNK_SIZE, file.size);
      const result = await sendChunk(id, file.slice(offset, end), offset, (bytes) => onProgress(bytes, id), signal);
      offset = result.offset;
      onProgress(offset, id);
    }
    return platformApi(`/uploads/${encodeURIComponent(id)}/finalize`, { method: 'POST' });
  } catch (error) {
    if (signal.aborted && id) await platformApi(`/uploads/${encodeURIComponent(id)}`, { method: 'DELETE' }).catch(() => {});
    throw error;
  }
}
