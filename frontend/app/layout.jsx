import "./globals.css";
import "./chat.css";

export const metadata = {
  title: "Palades",
  description: "Retrieval-Augmented Generation over enterprise knowledge bases",
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
