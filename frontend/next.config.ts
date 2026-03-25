import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: build produces an `out/` directory that FastAPI serves
  // directly from port 8000 — no separate Node.js server needed.
  output: "export",
  // Required when serving static exports through a proxying web server.
  images: { unoptimized: true },
};

export default nextConfig;
