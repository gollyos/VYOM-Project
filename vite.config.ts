import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

const host = process.env.TAURI_DEV_HOST;

// Stamped at config load so every build carries a distinguishable id
// in the app header (see vyom-experience.tsx diagnostics).
process.env.VITE_VYOM_BUILD_ID =
  process.env.VITE_VYOM_BUILD_ID ?? new Date().toISOString().slice(5, 16).replace(/[-T:]/g, '');

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/three") || id.includes("node_modules/@react-three")) {
            return "spatial-runtime";
          }
          if (id.includes("node_modules/react")) return "react-runtime";
          if (id.includes("node_modules/lucide-react")) return "icons";
          return undefined;
        },
      },
    },
  },
});
