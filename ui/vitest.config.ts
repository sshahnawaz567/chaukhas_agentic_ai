import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    // Tests run on the scripted mock data; adapters are tested against recorded API responses.
    env: { VITE_USE_MOCK: "true" },
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
