/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output: bundles only the production dependency subset
  // Next.js actually needs into .next/standalone, so the Docker image
  // (see Dockerfile) doesn't have to ship the full node_modules tree.
  output: "standalone",
};

module.exports = nextConfig;
