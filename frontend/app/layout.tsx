import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import InstrumentProvider from "@/components/InstrumentProvider";
import { AuthProvider } from "@/contexts/AuthContext";
import { AppShell } from "@/components/shell/AppShell";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Hand Of Midas",
  description: "Multi-Asset Algorithmic Trading Engine",
  icons: {
    icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🤚</text></svg>",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full`}
      style={{
        // Geist's variable -> Tailwind v4 theme tokens. Inline so the @theme
        // tokens resolve to the right CSS variable name on first paint.
        ["--font-sans" as string]: "var(--font-geist-sans)",
        ["--font-mono" as string]: "var(--font-geist-mono)",
      }}
    >
      <body className="min-h-full">
        <AuthProvider>
          <InstrumentProvider>
            <AppShell>{children}</AppShell>
          </InstrumentProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
