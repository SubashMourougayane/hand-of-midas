import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import InstrumentProvider from "@/components/InstrumentProvider";
import { AuthProvider } from "@/contexts/AuthContext";
import { AppShell } from "@/components/shell/AppShell";

export const dynamic = "force-dynamic";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
  display: "swap",
});

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
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable} h-full`}>
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
