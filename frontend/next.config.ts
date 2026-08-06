import type { NextConfig } from "next";

// S6: hardening headers applied to every route. Kept in sync with the backend
// SecurityHeadersMiddleware. The per-request nonce CSP lives in src/proxy.ts.
const SECURITY_HEADERS = [
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  // output: "standalone" is for Docker; Vercel uses its own adapter

  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },

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
