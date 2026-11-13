import { PLATFORM_BASE_URL } from '../../config/services.js';

export async function platformApi(path, options = {}) {
  let response;
  try {
    response = await fetch(`${PLATFORM_BASE_URL}${path}`, {
      ...options,
      headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
    });
  } catch { throw new Error('Platform API is offline. Start Branch Exterior on port 8011.'); }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return response.json();
}

export const useCases = [
  ['vault_access', 'Vault Access'], ['branch_exterior', 'Branch Exterior'],
  ['grill_gate', 'Gate & Mesh'], ['face_mask', 'Face Mask'],
];
