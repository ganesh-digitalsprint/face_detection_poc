import client from './client.js';

// GET /api/v1/health -> { status: "ok" | "degraded", service, database, qdrant }
export const getHealth = () => client.get('/api/v1/health').then((r) => r.data);
