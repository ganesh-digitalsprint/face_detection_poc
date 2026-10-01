import client from './client.js';

const imageForm = (file) => {
  const data = new FormData();
  data.append('image', file);
  return data;
};

// -> { faces_detected, faces: [{ bbox: {x,y,width,height}, detection_confidence|null, ... }] }
export const detectFaces = (file) =>
  client.post('/api/v1/faces/detect', imageForm(file)).then((r) => r.data);

// -> JPEG blob
export const detectFacesAnnotated = (file) =>
  client
    .post('/api/v1/faces/detect/image', imageForm(file), { responseType: 'blob' })
    .then((r) => r.data);
