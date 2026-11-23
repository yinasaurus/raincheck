import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true, host: "127.0.0.1" },
  test: {
    environment: "jsdom",
    globals: false,
    exclude: ["e2e/**", "node_modules/**"],
  },
});
