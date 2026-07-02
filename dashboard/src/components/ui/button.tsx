import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-ds-sm text-ds-sm font-medium transition-colors duration-ds focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-glass-border disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-ink-primary text-bg-base hover:bg-white",
        glass: "glass text-ink-primary hover:text-white hover:shadow-ds-hover",
        ghost: "text-ink-secondary hover:text-ink-primary hover:bg-glass",
        outline: "border border-glass-border text-ink-secondary hover:text-ink-primary hover:bg-glass",
      },
      size: {
        sm: "h-8 px-3",
        default: "h-9 px-4",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: { variant: "glass", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  }
);
Button.displayName = "Button";

export { buttonVariants };
