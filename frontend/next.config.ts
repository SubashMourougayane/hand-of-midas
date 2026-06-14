import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.0.101", "localhost", "127.0.0.1"],
  async rewrites() {
    const apiTarget = process.env.NODE_ENV === "production"
      ? "http://localhost:5053"
      : "https://midas.subashtrades.in";
    return [
      {
        source: "/api/oil-micro/:path*",
        destination: `${process.env.NODE_ENV === "production" ? "http://localhost:5056" : "http://localhost:5056"}/api/oil-micro/:path*`,
      },
      {
        source: "/api/oil/:path*",
        destination: `${process.env.NODE_ENV === "production" ? "http://localhost:5054" : "https://midas.subashtrades.in"}/api/oil/:path*`,
      },
      {
        source: "/api/micro/:path*",
        destination: `${process.env.NODE_ENV === "production" ? "http://localhost:5055" : "https://midas.subashtrades.in"}/api/micro/:path*`,
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
