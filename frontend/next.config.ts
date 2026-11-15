import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Docker image sets BUILD_STANDALONE=1 to get a self-contained server in .next/standalone.
  // Local `npm run build` + `npm run start` keep the normal output.
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,
  experimental: {
    agentFeedback: true,
    // Screens render in the browser after sign-in, so only opted-in segments are validated.
    instantInsights: { validationLevel: "manual-warning" },
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
