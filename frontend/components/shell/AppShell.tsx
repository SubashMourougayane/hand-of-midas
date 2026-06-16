"use client";
import { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { TopBar } from "./TopBar";
import { SectionNav, SectionNavMobile } from "./SectionNav";

const PUBLIC_PATHS = ["/", "/login", "/uikit", "/report", "/playbook", "/deck", "/robustness", "/journey", "/logo-lab"];

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const isPublic = PUBLIC_PATHS.some((p) => path === p || path.startsWith(`${p}/`));

  if (isPublic) {
    return <>{children}</>;
  }

  return (
    <div className="flex flex-col w-full min-h-screen bg-[var(--color-bg)]">
      <TopBar />
      <div className="flex flex-1 min-h-0">
        <SectionNav />
        <main
          id="content"
          className="flex-1 min-w-0 overflow-auto pb-[68px] md:pb-0"
        >
          {children}
        </main>
      </div>
      <SectionNavMobile />
    </div>
  );
}
