import type { NextConfig } from "next";

// The terminal uses only the public API. In development and in the plain compose setup the API is
// reached through this rewrite; behind the production proxy, /api is routed to the API directly.
const apiUrl = process.env.AUREX_API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  poweredByHeader: false,
  // The terminal renders in the browser after the session is known, so its pages have nothing to
  // prerender. Instant-navigation insights are limited to segments that opt in.
  experimental: { instantInsights: { validationLevel: "manual-warning" } },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
  async headers() {
    const production = process.env.NODE_ENV === "production";
    return [
      {
        source: "/:path*",
        headers: [
          ...(production
            ? [{
                key: "Content-Security-Policy",
                value: [
                  "default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'",
                  "img-src 'self' data: blob:", "font-src 'self' data:", "connect-src 'self'",
                  "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'", "object-src 'none'",
                ].join("; "),
              }, { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
            : []),
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
