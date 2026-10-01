import client from './client.js';

// -> { faces_detected, recognized_faces: [{ matched, person_code, name, distance, similarity, bbox, ... }], processing_time_ms }
export const identifyFaces = (file) => {
  const data = new FormData();
  data.append('image', file);
  return client.post('/api/v1/recognition/identify', data).then((r) => r.data);
};

// -> { matched, distance, similarity, threshold }
export const verifyFace = (personCode, file) => {
  const data = new FormData();
  data.append('person_code', personCode);
  data.append('image', file);
  return client.post('/api/v1/recognition/verify', data).then((r) => r.data);
};

// -> video/mp4 blob (FileResponse).
export const recognizeVideo = (file) => {
  const data = new FormData();
  data.append('video', file);
  return client
    .post('/api/v1/recognition/video', data, { responseType: 'blob', timeout: 0 })
    .then((r) => r.data);
};
