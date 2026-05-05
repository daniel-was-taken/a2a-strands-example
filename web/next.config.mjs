/** @type {import('next').NextConfig} */
// The frontend is built to a fully static bundle that FastAPI serves from
// `/static`. Using `output: 'export'` emits plain HTML/JS/CSS into `web/out/`.
// `assetPrefix` ensures every hashed asset is requested under `/static/...`
// (FastAPI mounts the export dir there), and `trailingSlash` keeps the
// exported HTML routes compatible with a static file server.
const ASSET_PREFIX = process.env.NEXT_PUBLIC_ASSET_PREFIX ?? "/static";

const nextConfig = {
  output: "export",
  reactStrictMode: true,
  trailingSlash: true,
  images: { unoptimized: true },
  assetPrefix: ASSET_PREFIX,
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? "",
  },
};

export default nextConfig;
