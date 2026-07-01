import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // output: "standalone" is for Docker; Vercel uses its own adapter

  // The legacy /dashboard/* shim tree and /auth/signup were deleted; redirect
  // old bookmarks/emails to the single (app) namespace. These run server-side
  // at request time (no auth needed).
  async redirects() {
    return [
      { source: "/dashboard", destination: "/history", permanent: true },
      { source: "/dashboard/analyses", destination: "/history", permanent: true },
      {
        source: "/dashboard/analyses/:id",
        destination: "/analyses/:id",
        permanent: true,
      },
      { source: "/dashboard/cost", destination: "/cost", permanent: true },
      {
        source: "/dashboard/batch/:path*",
        destination: "/batch/:path*",
        permanent: true,
      },
      { source: "/dashboard/keys", destination: "/settings/developer", permanent: true },
      {
        source: "/dashboard/reconstruct",
        destination: "/reconstruct",
        permanent: true,
      },
      { source: "/auth/signup", destination: "/signup", permanent: true },
      // API keys are demoted to Settings → Developer; redirect old bookmarks.
      { source: "/keys", destination: "/settings/developer", permanent: true },
      { source: "/settings", destination: "/settings/developer", permanent: false },
    ];
  },
};

export default nextConfig;
