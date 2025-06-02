// ui/app/layout.tsx
import "./globals.css";

export const metadata = {
  title: "Human-in-the-Loop Review",
  description: "Review low-confidence matches from Wiraa.ir vs Torob"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
