import "./globals.css";
import "./chat.css";

const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "https://pleiades-ppvc.onrender.com";

export const metadata = {
  metadataBase: new URL(SITE),
  title: "Pleiades",
  description:
    "Enterprise support answers grounded in your own documents, with a citation on every claim.",
  applicationName: "Pleiades",
  icons: {
    apple: "/apple-icon.png",
  },
  openGraph: {
    title: "Pleiades",
    description:
      "Enterprise support answers grounded in your own documents, with a citation on every claim.",
    url: SITE,
    siteName: "Pleiades",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "Pleiades" }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Pleiades",
    description: "Enterprise support answers grounded in your own documents.",
    images: ["/og.png"],
  },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#050914",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" data-theme="dark">
      <body>
        <div className="scene" aria-hidden="true">
          <div className="scene__blob scene__blob--1" />
          <div className="scene__blob scene__blob--2" />
          <div className="scene__blob scene__blob--3" />
        </div>
        {children}
      </body>
    </html>
  );
}
