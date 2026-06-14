"use client";
import { useState } from "react";
import {
  Button,
  Card,
  Stat,
  Badge,
  Tabs,
  Sheet,
  Skeleton,
  Table,
  StatusDot,
  Tooltip,
  EmptyState,
  PageHeader,
  Sparkline,
  type Column,
} from "@/components/ui";

interface DemoTrade {
  id: string;
  symbol: string;
  side: "LONG" | "SHORT";
  entry: number;
  pnl: number;
}

const DEMO_TRADES: DemoTrade[] = [
  { id: "GD-MI-1", symbol: "XAU/USD", side: "LONG", entry: 4196.10, pnl: 12.40 },
  { id: "OIL-AS-2", symbol: "BCO/USD", side: "SHORT", entry: 86.42, pnl: -8.20 },
  { id: "GD-MA-3", symbol: "XAU/USD", side: "LONG", entry: 4198.55, pnl: 24.10 },
];

const tradeCols: Column<DemoTrade>[] = [
  { key: "id", header: "Ref", cell: (r) => <span className="num text-[var(--color-text-muted)]">{r.id}</span> },
  { key: "symbol", header: "Symbol", cell: (r) => r.symbol },
  {
    key: "side",
    header: "Side",
    cell: (r) => <Badge tone={r.side === "LONG" ? "win" : "loss"}>{r.side}</Badge>,
  },
  { key: "entry", header: "Entry", align: "right", cell: (r) => <span className="num">{r.entry.toFixed(2)}</span> },
  {
    key: "pnl",
    header: "P&L",
    align: "right",
    cell: (r) => (
      <span className={`num font-semibold ${r.pnl >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
        {r.pnl >= 0 ? "+" : ""}{r.pnl.toFixed(2)}
      </span>
    ),
  },
];

export default function UIKitPage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [tab, setTab] = useState("buttons");

  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)] p-6 md:p-10 max-w-[1100px] mx-auto">
      <PageHeader
        title="UI Kit"
        description="Component primitives for the fe-remodel branch. Hidden gallery route — not linked from nav."
        breadcrumb="Internal · /_uikit"
        actions={
          <>
            <Button variant="ghost" size="sm">Docs</Button>
            <Button variant="primary" size="sm">Open Storybook</Button>
          </>
        }
      />

      <Tabs.Root value={tab} onValueChange={setTab} className="mt-2">
        <Tabs.List>
          <Tabs.Trigger value="buttons">Buttons</Tabs.Trigger>
          <Tabs.Trigger value="cards">Cards & Stats</Tabs.Trigger>
          <Tabs.Trigger value="badges">Badges</Tabs.Trigger>
          <Tabs.Trigger value="tables">Tables</Tabs.Trigger>
          <Tabs.Trigger value="overlays">Overlays</Tabs.Trigger>
          <Tabs.Trigger value="states">States</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Panel value="buttons" className="flex flex-col gap-4">
          <Card padded>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary">Primary</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="destructive">Destructive</Button>
              <Button variant="primary" loading>Loading</Button>
              <Button variant="secondary" disabled>Disabled</Button>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button size="sm">Small</Button>
              <Button size="md">Medium</Button>
              <Button size="lg">Large</Button>
            </div>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="cards" className="flex flex-col gap-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card padded>
              <Stat label="Account NAV" value="£12,481.20" tone="neutral" />
            </Card>
            <Card padded>
              <Stat label="Today P&L" value="+£124.80" tone="win" trend="up" hint="2 trades closed" />
            </Card>
            <Card padded>
              <Stat label="Drawdown" value="-£420.00" tone="loss" trend="down" hint="peak £12,901.20" />
            </Card>
            <Card padded>
              <Stat label="Open Pos" value="1" tone="info" mono={false} hint="LONG · 2.0u" />
            </Card>
          </div>

          <Card>
            <Card.Header>
              <Card.Title>Equity Curve</Card.Title>
              <Sparkline values={[100, 102, 99, 104, 108, 105, 112, 118, 115, 122]} width={120} height={28} color="var(--color-win)" />
            </Card.Header>
            <Card.Body>
              <p className="text-[12px] text-[var(--color-text-dim)]">
                Sparkline auto-scales to data. <span className="num">+22.0%</span> over 10 sessions.
              </p>
            </Card.Body>
            <Card.Footer>
              <Button size="sm" variant="ghost">View detail</Button>
              <Button size="sm" variant="secondary">Export</Button>
            </Card.Footer>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="badges" className="flex flex-col gap-3">
          <Card padded>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="neutral">neutral</Badge>
              <Badge tone="win">win</Badge>
              <Badge tone="loss">loss</Badge>
              <Badge tone="info">info</Badge>
              <Badge tone="warn">warn</Badge>
              <Badge tone="system" systemColor="var(--color-sys-gold)">Gold Macro</Badge>
              <Badge tone="system" systemColor="var(--color-sys-gold-micro)">Gold Micro</Badge>
              <Badge tone="system" systemColor="var(--color-sys-oil)">Oil Macro</Badge>
              <Badge tone="system" systemColor="var(--color-sys-oil-micro)">Oil Micro</Badge>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Badge tone="win" variant="solid">solid</Badge>
              <Badge tone="win" variant="soft">soft</Badge>
              <Badge tone="win" variant="outline">outline</Badge>
            </div>
            <div className="mt-3 flex items-center gap-3 text-[12px]">
              <span className="inline-flex items-center gap-2"><StatusDot tone="win" pulse /> Live</span>
              <span className="inline-flex items-center gap-2"><StatusDot tone="info" /> Connecting</span>
              <span className="inline-flex items-center gap-2"><StatusDot tone="muted" /> Idle</span>
              <span className="inline-flex items-center gap-2"><StatusDot tone="loss" /> Error</span>
            </div>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="tables">
          <Card>
            <Card.Header>
              <Card.Title>Recent Trades</Card.Title>
              <Button size="sm" variant="ghost">Filter</Button>
            </Card.Header>
            <div className="p-3">
              <Table
                columns={tradeCols}
                rows={DEMO_TRADES}
                rowKey={(r) => r.id}
                onRowClick={(r) => console.log("clicked", r.id)}
                emptyState={<EmptyState title="No trades yet" />}
              />
            </div>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="overlays" className="flex flex-col gap-4">
          <Card padded>
            <div className="flex flex-wrap gap-3 items-center">
              <Button variant="primary" onClick={() => setSheetOpen(true)}>Open Sheet</Button>
              <Tooltip content="Click for trade detail" side="top">
                <Button variant="secondary">Hover me</Button>
              </Tooltip>
            </div>
          </Card>
          <Sheet open={sheetOpen} onClose={() => setSheetOpen(false)} title="Trade Detail · GD-MI-1">
            <div className="p-4 flex flex-col gap-3">
              <Stat label="P&L" value="+£12.40" tone="win" />
              <Stat label="Entry" value="4,196.10" />
              <Stat label="Exit" value="4,202.40" />
            </div>
          </Sheet>
        </Tabs.Panel>

        <Tabs.Panel value="states" className="flex flex-col gap-4">
          <Card padded>
            <div className="flex flex-col gap-3">
              <Skeleton width="60%" height={16} />
              <Skeleton width="80%" height={14} />
              <Skeleton width="40%" height={12} />
              <Skeleton width={120} height={120} rounded="md" />
            </div>
          </Card>
          <Card>
            <EmptyState
              title="No journal events"
              description="Events will appear here as the system trades. Check back during market hours."
              action={<Button size="sm" variant="primary">Run a backtest</Button>}
            />
          </Card>
        </Tabs.Panel>
      </Tabs.Root>
    </div>
  );
}
