/** @type {import('next').NextConfig} */
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Routes were renamed when /profile was split by job (UX plan §11.2). Permanent redirects
  // (308) keep bookmarks, emailed links and old `next=` targets working; the query is kept.
  async redirects() {
    return [
      { source: "/dashboard", destination: "/generate", permanent: true },
      { source: "/profile", destination: "/voices", permanent: true },
    ];
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Token-bearing pages must never leak the URL fragment via Referer.
      {
        source: "/:page(verify-email|reset-password)",
        headers: [{ key: "Referrer-Policy", value: "no-referrer" }],
      },
    ];
  },
};

export default nextConfig;
