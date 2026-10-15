import client from './client.js';

// -> { person_id, person_code, name, face_registered, model_name }
export const registerPerson = (personCode, name, file) => {
  const data = new FormData();
  data.append('person_code', personCode);
  data.append('name', name);
  data.append('image', file);
  return client.post('/api/v1/persons', data).then((r) => r.data);
};

// Multi-image capture uses the same Person registration service and vector store.
export const registerPersonFromImages = (personCode, name, files) => {
  const data = new FormData();
  data.append('person_code', personCode);
  data.append('name', name);
  files.forEach((file) => data.append('images', file));
  return client.post('/api/v1/persons/images', data).then((r) => r.data);
};
