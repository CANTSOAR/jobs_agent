import type { NextConfig } from "next";

// GitHub Pages serves this repo at /jobs_agent/, not the domain root, so the static
// export needs every route/asset path prefixed with the repo name. Only set in the CI
// build env so local `npm run dev`/`npm run build` stay at root. Also exposed to client
// components as NEXT_PUBLIC_BASE_PATH (see src/lib/basePath.ts) for plain <img src>
// references, which basePath doesn't rewrite the way next/image or next/link do.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig: NextConfig = {
  output: 'export',
  basePath,
  trailingSlash: true,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  }
};

export default nextConfig;
