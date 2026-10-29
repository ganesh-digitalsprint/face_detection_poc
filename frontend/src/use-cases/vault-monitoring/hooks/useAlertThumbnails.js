import { useEffect, useState } from 'react';
import { getEvidenceAccess } from '../api/alerts.js';

/** Requests visible thumbnails once in a batch; signed URLs stay in component memory. */
export default function useAlertThumbnails(alerts) {
  const [urls, setUrls] = useState({});
  const ids = alerts.map((item) => item.primaryEvidenceId).filter(Boolean);
  const key = ids.join(',');
  useEffect(() => {
    let active = true;
    setUrls({});
    if (!ids.length) return () => { active = false; };
    getEvidenceAccess(ids, 'thumb').then((response) => {
      if (active) setUrls(Object.fromEntries((response.items || []).filter((item) => item.url).map((item) => [item.id, item.url])));
    }).catch(() => { if (active) setUrls({}); });
    return () => { active = false; };
  }, [key]);
  return urls;
}
