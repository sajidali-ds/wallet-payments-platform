import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the browser talks to the Vite server, which forwards API paths to the gateway.
// That keeps everything on one origin (no CORS in the services) exactly like production, where
// the frontend container / Caddy sends the same paths to the gateway.
const gateway = process.env.VITE_GATEWAY_URL ?? "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "^/(auth|wallets|transfers|admin|notifications)(/|$)": {
        target: gateway,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
