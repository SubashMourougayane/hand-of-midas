import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-ds-xs font-medium uppercase tracking-wide",
  {
    variants: {
      tone: {
        neutral: "bg-glass border-glass-border text-ink-secondary",
        bull: "bg-bull/10 border-bull/40 text-bull",
        bear: "bg-bear/10 border-bear/40 text-bear",
        warn: "bg-warn/10 border-warn/40 text-warn",
        info: "bg-info/10 border-info/40 text-info",
      },
    },
    defaultVariants: { tone: "neutral" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
