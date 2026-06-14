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
  Display,
  CountUp,
  MarqueeTicker,
  Reveal,
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
  const [tab, setTab] = useState("design");
  const [pnl, setPnl] = useState(12481.20);

  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)] p-6 md:p-10 max-w-[1100px] mx-auto">
      <PageHeader
        title="UI Kit"
        description="Design language gallery for the fe-remodel branch. Old-money trading desk: warm-black, brass accents, serif headlines, animated stats."
        breadcrumb="Internal · /uikit"
        size="lg"
        actions={
          <>
            <Button variant="ghost" size="sm">Docs</Button>
            <Button variant="primary" size="sm">Deploy preview</Button>
          </>
        }
      />

      <Tabs.Root value={tab} onValueChange={setTab} className="mt-2">
        <Tabs.List>
          <Tabs.Trigger value="design">Design language</Tabs.Trigger>
          <Tabs.Trigger value="buttons">Buttons</Tabs.Trigger>
          <Tabs.Trigger value="cards">Cards & Stats</Tabs.Trigger>
          <Tabs.Trigger value="badges">Badges</Tabs.Trigger>
          <Tabs.Trigger value="tables">Tables</Tabs.Trigger>
          <Tabs.Trigger value="overlays">Overlays</Tabs.Trigger>
          <Tabs.Trigger value="states">States</Tabs.Trigger>
        </Tabs.List>

        {/* DESIGN LANGUAGE — fonts, colors, motion */}
        <Tabs.Panel value="design" className="flex flex-col gap-5">
          <Card padded>
            <div className="flex flex-col gap-2 mb-3">
              <span className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Display</span>
              <Display size="xl" italic>Hand of Midas</Display>
              <Display size="md">Trades · Today's positions</Display>
              <p className="text-[12px] text-[var(--color-text-dim)]">Instrument Serif · for page titles, hero copy, narrative numbers.</p>
            </div>
            <div className="hom-rule my-4" />
            <div className="flex flex-col gap-2">
              <span className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)]">UI / Body — Geist Sans</span>
              <p className="text-[14px] text-[var(--color-text)]">The quick brown fox jumped over the lazy dog. <span className="text-[var(--color-text-dim)]">— body copy</span></p>
              <span className="text-[11px] uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Section / Label</span>
              <p className="text-[12px] text-[var(--color-text-dim)]">Buttons, navigation, table headers, breadcrumbs.</p>
            </div>
            <div className="hom-rule my-4" />
            <div className="flex flex-col gap-2">
              <span className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Data — Geist Mono · tabular-nums</span>
              <p className="num text-[14px]">$4,197.42  +£124.80  −$420.00  61.1%  +2.0R  4d 12h 03m</p>
            </div>
          </Card>

          <Card padded>
            <span className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] mb-3 block">Palette</span>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Swatch name="Brass" cssVar="--color-brass" hex="#d4a464" />
              <Swatch name="Brass hi" cssVar="--color-brass-hi" hex="#e8be7e" />
              <Swatch name="Win" cssVar="--color-win" hex="#5fb675" />
              <Swatch name="Loss" cssVar="--color-loss" hex="#d8595c" />
              <Swatch name="bg" cssVar="--color-bg" hex="#0c0a08" />
              <Swatch name="surface 1" cssVar="--color-surface-1" hex="#161310" />
              <Swatch name="surface 2" cssVar="--color-surface-2" hex="#1f1a15" />
              <Swatch name="border-hi" cssVar="--color-border-hi" hex="#3d3327" />
            </div>
          </Card>

          <Card padded>
            <span className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] mb-3 block">Live ticker (marquee)</span>
            <MarqueeTicker speed={48}>
              <span className="num text-[12px]"><span className="text-[var(--color-text-muted)]">XAU/USD </span>$4,197.42 <span className="text-[var(--color-win)]">+0.12%</span></span>
              <span className="num text-[12px]"><span className="text-[var(--color-text-muted)]">BCO/USD </span>$86.42 <span className="text-[var(--color-loss)]">−0.34%</span></span>
              <span className="num text-[12px]"><span className="text-[var(--color-text-muted)]">SPX </span>5,742.10 <span className="text-[var(--color-win)]">+0.08%</span></span>
              <span className="num text-[12px]"><span className="text-[var(--color-text-muted)]">DXY </span>104.21 <span className="text-[var(--color-loss)]">−0.21%</span></span>
              <span className="num text-[12px]"><span className="text-[var(--color-text-muted)]">VIX </span>14.87 <span className="text-[var(--color-loss)]">−1.42%</span></span>
              <span className="num text-[12px]"><span className="text-[var(--color-text-muted)]">UST10Y </span>4.118% <span className="text-[var(--color-win)]">+2bp</span></span>
            </MarqueeTicker>
          </Card>

          <Card padded>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Animated stat</span>
              <Button size="sm" variant="ghost" onClick={() => setPnl(Math.random() * 25000)}>
                Randomize
              </Button>
            </div>
            <Stat
              label="Account NAV"
              value={pnl}
              animate
              decimals={2}
              prefix="£"
              size="lg"
              tone="brass"
              hint={<span><CountUp value={pnl} prefix="≈ ₹" decimals={0} /> at today's rate</span>}
            />
          </Card>
        </Tabs.Panel>

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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 hom-stagger-children">
            <Card padded lift className="hom-stagger">
              <Stat label="Account NAV" value={12481.20} animate decimals={2} prefix="£" tone="brass" />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat label="Today P&L" value={124.80} animate decimals={2} prefix="+£" tone="win" trend="up" hint="2 trades closed" />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat label="Drawdown" value={420.00} animate decimals={2} prefix="−£" tone="loss" trend="down" hint={<>peak <span className="num">£12,901.20</span></>} />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat label="Open Pos" value={1} animate mono={false} tone="info" hint="LONG · 2.0u" />
            </Card>
          </div>

          <Card lift>
            <Card.Header>
              <Card.Title>Equity Curve</Card.Title>
              <Sparkline values={[100, 102, 99, 104, 108, 105, 112, 118, 115, 122]} width={120} height={28} color="var(--color-brass)" fillOpacity={0.20} />
            </Card.Header>
            <Card.Body>
              <p className="text-[12px] text-[var(--color-text-dim)]">
                Sparkline auto-scales. <span className="num">+22.0%</span> over 10 sessions.
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
              <Badge tone="warn">brass</Badge>
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
          <Reveal delay={150}>
            <Card padded>
              <p className="text-[12px] text-[var(--color-text-dim)]">This card faded in via &lt;Reveal delay={150}&gt;.</p>
            </Card>
          </Reveal>
        </Tabs.Panel>
      </Tabs.Root>
    </div>
  );
}

function Swatch({ name, cssVar, hex }: { name: string; cssVar: string; hex: string }) {
  return (
    <div className="flex items-center gap-2.5 rounded-[5px] border border-[var(--color-border)] p-2">
      <div
        className="w-9 h-9 rounded-[3px] flex-shrink-0 border border-[var(--color-border)]"
        style={{ background: `var(${cssVar})` }}
      />
      <div className="flex flex-col leading-tight">
        <span className="text-[12px] text-[var(--color-text)]">{name}</span>
        <span className="num text-[10px] text-[var(--color-text-muted)]">{hex}</span>
      </div>
    </div>
  );
}
