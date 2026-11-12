export function parseRtspUrl(input) {
  const url = new URL(input);
  if (!['rtsp:', 'rtsps:'].includes(url.protocol) || !url.hostname) throw new Error('Only RTSP/RTSPS URLs are allowed');
  return { scheme: url.protocol.slice(0, -1), host: url.hostname.replace(/^\[|\]$/g, ''), rtsp_port: Number(url.port || 554), username: decodeURIComponent(url.username), password: decodeURIComponent(url.password), custom_path: `${url.pathname}${url.search}` };
}

export function maskedPreview({ scheme = 'rtsp', host, rtsp_port = 554, username = '', password = '', stream = 1, template_key = 'hikvision', custom_path = '' }, templates = {}) {
  const pattern = template_key === 'generic' ? custom_path : templates[template_key] || '';
  const path = pattern.replaceAll('{channel}', '1').replaceAll('{stream}', String(stream));
  const user = username ? `${encodeURIComponent(username)}${password ? ':••••••••' : ''}@` : '';
  return `${scheme}://${user}${host || 'host'}:${rtsp_port}${path}`;
}
