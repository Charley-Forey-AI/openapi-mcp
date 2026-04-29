import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Production build targets HTTPS://<host>/endpoint-picker/ (see README). Local dev uses "/".
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/endpoint-picker/" : "/",
}));
