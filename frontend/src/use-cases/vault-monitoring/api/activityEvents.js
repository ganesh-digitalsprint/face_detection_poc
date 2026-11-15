import client from '../../../api/client.js';

/** @typedef {{id:string,type:string,session_id:string,camera_id:string,source_id:string,video_timestamp_seconds:number,created_at:string,track_ids:number[],person_count:number,zone_id:string|null,description:string,evidence_reference:string|null,source:'webcam'|'cctv'|'upload',replay:boolean,test_mode:boolean,metadata:Record<string,unknown>}} ActivityEvent */
/** @typedef {{items:ActivityEvent[],total:number,limit:number,offset:number}} ActivityPage */
const root = '/api/v1/vault-room';
const key = import.meta.env?.VITE_VAULT_ROOM_API_KEY;
const headers = key ? { 'X-API-Key': key } : {};

/** @returns {Promise<ActivityPage>} */
export async function getActivityEvents(sessionId, params, signal) {
  const { data } = await client.get(`${root}/sessions/${encodeURIComponent(sessionId)}/activity-events`,
    { params, signal, headers, timeout: 15000 });
  if (!Array.isArray(data?.items) || !Number.isFinite(data.total)) throw new Error('The activity API returned an invalid event history.');
  return data;
}

/** @returns {Promise<ActivityEvent>} */
export const getActivityEvent = (id, signal) => client.get(`${root}/activity-events/${encodeURIComponent(id)}`,
  { signal, headers, timeout: 15000 }).then((response) => response.data);

/** Authenticated binary read; never put the API key in an image URL. */
export const getActivityEvidence = (id, signal) => client.get(`${root}/activity-events/${encodeURIComponent(id)}/evidence`,
  { signal, headers, responseType: 'blob', timeout: 15000 }).then((response) => response.data);
