import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Port 3000 (strict): Vault's CORS_ALLOW_ORIGINS default is http://localhost:3000.
//
// Alert Service access: the browser calls the same-origin path /alert-service/*, and this dev/preview
// proxy forwards it to the Alert Service with the OPERATOR bearer token added here, on the server side.
// ALERT_SERVICE_URL / ALERT_SERVICE_OPERATOR_TOKEN are deliberately not VITE_-prefixed, so Vite never
// copies them into the browser bundle. A deployed static build needs an equivalent reverse proxy.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const token = env.ALERT_SERVICE_OPERATOR_TOKEN || '';
  const proxy = {
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
