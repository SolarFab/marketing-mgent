import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Signal — Content Agent",
  description: "A self-marketing agent for content-constrained businesses.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full bg-neutral-50 text-neutral-900">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
