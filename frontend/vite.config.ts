import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
        ...(env.VITE_DEMO_JANA_PROXY === '/jana-demo' ? { '/jana-demo': {
          target: 'http://127.0.0.1:8002', changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/jana-demo/, ''),
          configure: (proxy: import('vite').HttpProxy.Server) => {
            proxy.on('proxyReq', request => { request.removeHeader('authorization'); request.removeHeader('cookie'); });
          },
        } } : {}),
      },
    },
    preview: { port: 4173 },
  };
});
