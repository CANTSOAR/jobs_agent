import type { NextConfig } from "next";

// GitHub Pages serves this repo at /jobs_agent/, not the domain root, so the static
// export needs every route/asset path prefixed with the repo name. Only applied in
// the CI build (GITHUB_PAGES=true) so local `npm run dev`/`npm run build` stay at root.
const isGithubPages = process.env.GITHUB_PAGES === "true";
const basePath = isGithubPages ? "/jobs_agent" : "";

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
