import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const apiTarget = process.env.NODE_ENV === "production"
      ? "http://localhost:5053"
      : "https://midas.subashtrades.in";
    return [
      {
        source: "/api/oil/:path*",
        destination: `${process.env.NODE_ENV === "production" ? "http://localhost:5054" : "https://midas.subashtrades.in"}/api/oil/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${apiTarget}/api/:path*`,
      },
    ];
  },
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
