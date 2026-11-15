import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

// Port 3000 (strict): Vault's CORS_ALLOW_ORIGINS default is http://localhost:3000.
//
// Alert Service access: the browser calls the same-origin path /alert-service/*, and this dev/preview
// proxy forwards it to the Alert Service with the OPERATOR bearer token added here, on the server side.
// ALERT_SERVICE_URL / ALERT_SERVICE_OPERATOR_TOKEN are deliberately not VITE_-prefixed, so Vite never
// copies them into the browser bundle. A deployed static build needs an equivalent reverse proxy.
const demoKeyPath = resolve(process.cwd(), '..', 'backend', 'services', 'platform_data', 'local-demo.key');

function localDemoKey() {
  mkdirSync(dirname(demoKeyPath), { recursive: true });
  try {
    writeFileSync(demoKeyPath, randomBytes(32).toString('hex'), { flag: 'wx', mode: 0o600 });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }
  return readFileSync(demoKeyPath, 'ascii').trim();
}

const isLoopback = (address = '') => ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(address);

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const token = env.ALERT_SERVICE_OPERATOR_TOKEN || '';
  const platformTarget = env.PLATFORM_SERVICE_URL || 'http://127.0.0.1:8011';
  const demoKey = command === 'serve' && !env.FEDBANK_PLATFORM_ADMIN_KEY &&
    ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(platformTarget).hostname)
    ? localDemoKey() : '';
  const proxy = {
    '/platform': {
      target: platformTarget,
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/platform/, '/api/platform'),
      configure: (platformProxy) => {
        platformProxy.on('proxyReq', (proxyReq, request) => {
          proxyReq.removeHeader('X-Platform-Admin-Key');
          if (!isLoopback(request.socket.remoteAddress)) return;
          const key = env.FEDBANK_PLATFORM_ADMIN_KEY || demoKey;
          if (key) proxyReq.setHeader('X-Platform-Admin-Key', key);
        });
      },
    },
    '/alert-service': {
      target: env.ALERT_SERVICE_URL || 'http://127.0.0.1:8012',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/alert-service/, ''),
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  };
  return {
    plugins: [react(), tailwindcss()],
    server: { port: 3000, strictPort: true, proxy },
    preview: { port: 3000, strictPort: true, proxy },
  };
});
