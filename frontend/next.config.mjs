/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a self-contained server bundle only when explicitly requested (the
  // production Docker image sets NEXT_OUTPUT=standalone). Left off for local
  // `next build` because standalone file-tracing needs symlink privileges that
  // are not available by default on Windows.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  reactStrictMode: true,
};

export default nextConfig;
