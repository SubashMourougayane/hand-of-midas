import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.0.101", "localhost", "127.0.0.1"],
  // No /api rewrites — the frontend hits the hosted API directly via
  // NEXT_PUBLIC_API_BASE (default: https://midas.subashtrades.in). The
  // backend has CORS open for http://localhost:3000 and the prod domain.
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Pragma", value: "no-cache" },
          { key: "Expires", value: "0" },
        ],
      },
    ];
  },
};

export default nextConfig;
