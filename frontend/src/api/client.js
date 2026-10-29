import axios from 'axios';
import { VAULT_BASE_URL } from '../config/services.js';
import { normalizeError } from '../utils/errors.js';

export const API_BASE_URL = VAULT_BASE_URL;

const client = axios.create({ baseURL: API_BASE_URL });

client.interceptors.response.use(
  (response) => response,
  async (error) => Promise.reject(await normalizeError(error)),
);

/** Absolute URL for resources the browser loads directly (e.g. MJPEG <img>). */
export const apiUrl = (path) => `${API_BASE_URL}${path}`;

export default client;
