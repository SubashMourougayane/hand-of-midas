import type { Metadata } from "next";
import "./globals.css";
import InstrumentProvider from "@/components/InstrumentProvider";
import { AuthProvider } from "@/contexts/AuthContext";

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
    <html lang="en" className="h-full">
      <body className="min-h-full flex">
        <AuthProvider>
          <InstrumentProvider>{children}</InstrumentProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
