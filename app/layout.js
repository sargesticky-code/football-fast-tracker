import "./globals.css";

export const metadata = {
  title: "Fast Tracker 2026",
  description: "HKJC-first football intelligence",
  manifest: "/manifest.webmanifest",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#07110e",
};

export default function RootLayout({ children }) {
  return (
    <html lang="zh-HK">
      <body>{children}</body>
    </html>
  );
}
