import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [
    react(),
    viteSingleFile(),
    {
      name: "copy-to-python-static",
      closeBundle() {
        const src = path.join(__dirname, "dist/index.html");
        const destDir = path.join(__dirname, "../../src/openapi_mcp_builder/static");
        const dest = path.join(destDir, "endpoint_picker_mcp.html");
        mkdirSync(destDir, { recursive: true });
        copyFileSync(src, dest);
      },
    },
  ],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
