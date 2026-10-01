const DEFAULT_MESSAGES = {
  400: 'Invalid image or request.',
  404: 'Requested person or stream was not found.',
  405: 'This feature is not available on the connected backend.',
  409: 'Conflict with existing data (duplicate person or no enrolled face).',
  413: 'Uploaded file exceeds the allowed size.',
  422: 'The request could not be processed.',
  500: 'Server encountered an unexpected error.',
  503: 'Camera/CCTV stream could not be started.',
};

/** Extract the backend `detail` (string or FastAPI validation list) when safe. */
function extractDetail(data) {
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d?.msg).filter(Boolean).join('; ') || null;
  }
  return null;
}

/** Convert any thrown error into `{ status, message }` safe to show to users. */
export function describeError(error, overrides = {}) {
  if (error?.userMessage && !overrides) return { status: error.status ?? null, message: error.userMessage };
  const status = error?.response?.status;
  if (!status) {
    return {
      status: null,
      message: 'Cannot reach the API. Check that the backend is running and VITE_API_BASE_URL is correct.',
    };
  }
  const detail = extractDetail(error.response.data);
  const message = detail || overrides[status] || DEFAULT_MESSAGES[status] || `Request failed (HTTP ${status}).`;
  return { status, message };
}

/** Axios interceptor helper: JSON error bodies of blob endpoints arrive as Blob; decode them. */
export async function normalizeError(error) {
  const data = error?.response?.data;
  if (data instanceof Blob) {
    try {
      error.response.data = JSON.parse(await data.text());
    } catch {
      error.response.data = null;
    }
  }
  return error;
}
