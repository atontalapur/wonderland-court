import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const isStaticMode = process.env.VITE_STATIC_MODE === "true";

export default defineConfig({
  plugins: [react()],
  base: isStaticMode ? "./" : "/",
  build: {
    outDir: isStaticMode
      ? "dist-pages"
      : "../src/wonderland_court/courtroom/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
