import axios from 'axios';
import { VAULT_BASE_URL } from '../config/services.js';

const env = import.meta.env ?? {};
const registry = axios.create({
  baseURL: `${VAULT_BASE_URL}/api/v1/regions`,
  headers: env.VITE_VAULT_ROOM_API_KEY ? { 'X-API-Key': env.VITE_VAULT_ROOM_API_KEY } : {},
});

registry.interceptors.response.use((response) => response.data);

export const regionsRegistryApi = {
  get: (path) => registry.get(path),
  post: (path, body) => registry.post(path, body),
  patch: (path, body) => registry.patch(path, body),
  del: (path) => registry.delete(path),
};
