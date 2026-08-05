const dev = process.env.NODE_ENV === "development";
const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";

const config = {
  reactStrictMode: true,
  images: { unoptimized: true },
  ...(dev
    ? {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
        },
      }
    : { output: "export" }),
};

export default config;
