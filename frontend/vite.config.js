import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Port 3000 (strict): backend CORS_ALLOW_ORIGINS default is http://localhost:3000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 3000, strictPort: true },
});
