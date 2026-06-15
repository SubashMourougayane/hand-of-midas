"use client";
import { CSSProperties } from "react";
import { cn } from "./cn";

interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  rounded?: "sm" | "md" | "lg" | "full";
  className?: string;
}

const ROUND: Record<NonNullable<SkeletonProps["rounded"]>, string> = {
  sm: "rounded-[4px]",
  md: "rounded-[6px]",
  lg: "rounded-[10px]",
  full: "rounded-full",
};

export function Skeleton({
  width,
  height = 14,
  rounded = "sm",
  className,
}: SkeletonProps) {
  const style: CSSProperties = {
    width: width ?? "100%",
    height,
  };
  return (
    <div
      style={style}
      aria-hidden
      className={cn(
        "relative overflow-hidden bg-[var(--color-surface-2)]",
        ROUND[rounded],
        "before:content-[''] before:absolute before:inset-0",
        "before:bg-gradient-to-r before:from-transparent before:via-white/[0.04] before:to-transparent",
        "before:animate-[shimmer_1.4s_infinite]",
        className,
      )}
    >
      <style jsx>{`
        @keyframes shimmer {
          from { transform: translateX(-100%); }
          to { transform: translateX(100%); }
        }
      `}</style>
    </div>
  );
}
