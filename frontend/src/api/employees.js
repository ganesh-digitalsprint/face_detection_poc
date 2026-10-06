import client from './client.js';

const enc = encodeURIComponent;

// -> { id, employee_id, name, department, designation, created_at, updated_at }
export const createEmployee = (payload) =>
  client.post('/api/v1/employees', payload).then((r) => r.data);

// -> { employee_id, is_active, face_registered, authorized_by, authorization_reason, remarks, ... }
export const createAuthorization = (employeeId, payload) =>
  client.post(`/api/v1/employees/${enc(employeeId)}/authorization`, payload).then((r) => r.data);

// Backend field name is `images` (1-3 files) -> { message, employee_id, face_registered, images_enrolled }
export const enrollFace = (employeeId, files) => {
  const data = new FormData();
  files.forEach((file) => data.append('images', file));
  return client
    .post(`/api/v1/employees/${enc(employeeId)}/face-enrollment`, data)
    .then((r) => r.data);
};
