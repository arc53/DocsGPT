import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import svgr from 'vite-plugin-svgr';

// https://vitejs.dev/config/

// export default defineConfig(({ command, mode }) => {
//   // Load env file based on `mode` in the current working directory
//   const env = loadEnv(mode, process.cwd());
//   return {
//     plugins: [react(), svgr()],
//     define: {
//       'process.env': {},
//     },
//   };
// });

export default defineConfig({
  plugins: [react(), svgr()],
  define: {
    'process.env': {},
  },
});
