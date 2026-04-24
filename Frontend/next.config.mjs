import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot: __dirname,
  async rewrites() {
    const backendOrigin = process.env.BACKEND_ORIGIN ?? "127.0.0.1:8000";
    return [
      {
        source: "/advisor/:path*",
        destination: `http://${backendOrigin}/advisor/:path*`
      },
      {
        source: "/health",
        destination: `http://${backendOrigin}/health`
      }
    ];
  }
};

export default nextConfig;
