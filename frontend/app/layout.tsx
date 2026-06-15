import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono, Fraunces } from "next/font/google";
import "./globals.css";
import InstrumentProvider from "@/components/InstrumentProvider";
import { AuthProvider } from "@/contexts/AuthContext";
import { AppShell } from "@/components/shell/AppShell";

export const dynamic = "force-dynamic";

// IBM Plex Sans — UI body. Refined humanist sans with a custom feel.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

// IBM Plex Mono — numbers, code, mono labels.
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

// Fraunces — display headlines, italic-heavy. Editorial luxe.
const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  style: ["normal", "italic"],
  variable: "--font-fraunces",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Hand Of Midas",
  description: "Quantitative Commodities Trading",
  // Favicon comes from app/icon.svg (Next.js file convention). Spire mark
  // on a slate tile so it reads correctly on both light + dark browser tabs.
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable} ${fraunces.variable} h-full`}
      style={{
        ["--font-sans" as string]: "var(--font-plex-sans)",
        ["--font-mono" as string]: "var(--font-plex-mono)",
        ["--font-display" as string]: "var(--font-fraunces)",
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
