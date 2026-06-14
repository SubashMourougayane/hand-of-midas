"use client";
import {
  createContext,
  useContext,
  useState,
  ReactNode,
  HTMLAttributes,
  useCallback,
} from "react";
import { cn } from "./cn";

type Ctx = {
  value: string;
  setValue: (v: string) => void;
};

const TabsCtx = createContext<Ctx | null>(null);

function useTabs() {
  const ctx = useContext(TabsCtx);
  if (!ctx) throw new Error("Tabs.* must be used inside <Tabs.Root>");
  return ctx;
}

interface RootProps {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  children: ReactNode;
  className?: string;
}

function Root({ value, defaultValue = "", onValueChange, children, className }: RootProps) {
  const [internal, setInternal] = useState(defaultValue);
  const isControlled = value !== undefined;
  const current = isControlled ? value : internal;
  const setValue = useCallback(
    (v: string) => {
      if (!isControlled) setInternal(v);
      onValueChange?.(v);
    },
    [isControlled, onValueChange],
  );
  return (
    <TabsCtx.Provider value={{ value: current, setValue }}>
      <div className={cn("flex flex-col gap-3", className)}>{children}</div>
    </TabsCtx.Provider>
  );
}

function List({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex items-center gap-0.5 p-0.5 rounded-[6px]",
        "bg-[var(--color-surface-1)] border border-[var(--color-border)]",
        className,
      )}
      {...rest}
    />
  );
}

interface TriggerProps extends HTMLAttributes<HTMLButtonElement> {
  value: string;
}

function Trigger({ value, className, children, ...rest }: TriggerProps) {
  const ctx = useTabs();
  const active = ctx.value === value;
  return (
    <button
      role="tab"
      type="button"
      aria-selected={active}
      data-state={active ? "active" : "inactive"}
      onClick={() => ctx.setValue(value)}
      className={cn(
        "px-3 h-7 rounded-[4px] text-[12px] font-medium transition-colors",
        "outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-hi)]/60",
        active
          ? "bg-[var(--color-surface-3)] text-[var(--color-text)]"
          : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

interface PanelProps extends HTMLAttributes<HTMLDivElement> {
  value: string;
}

function Panel({ value, className, children, ...rest }: PanelProps) {
  const ctx = useTabs();
  if (ctx.value !== value) return null;
  return (
    <div role="tabpanel" className={className} {...rest}>
      {children}
    </div>
  );
}

export const Tabs = { Root, List, Trigger, Panel };
