"use client";
import { useInstrument } from "@/lib/instrument";
import { PageHeader, Card, Badge } from "@/components/ui";

const STRAT_COLOR: Record<string, string> = {
  alpha: "var(--color-info)",
  meanrev: "var(--color-win)",
  cross: "var(--color-warn)",
};

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[12px]">
      <span className="text-[var(--color-text-muted)]">{label}</span>
      <span className="text-[var(--color-text)] num text-right">{value}</span>
    </div>
  );
}

export default function SettingsPage() {
  const { instrument } = useInstrument();
  const isGold = instrument === "gold" || instrument === "micro";
  const symbol = isGold ? "XAU/USD" : "BCO/USD";

  return (
    <div className="p-3 sm:p-6 max-w-[1280px] mx-auto">
      <PageHeader
        title="Settings"
        description={`${isGold ? "GoldDigger" : "OilMiner"} — Strategy parameters and execution configuration (read-only)`}
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 hom-stagger-children">
        {/* Risk Allocation */}
        <Card className="hom-stagger" lift>
          <Card.Header>
            <Card.Title>Risk Allocation</Card.Title>
          </Card.Header>
          <div className="px-4 pb-4">
            <table className="w-full text-[12px]">
              <thead>
                <tr>
                  <th className="text-left py-2 text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)] font-medium">Strategy</th>
                  <th className="text-right py-2 text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)] font-medium">Risk %</th>
                  <th className="text-right py-2 text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)] font-medium">Max Position</th>
                </tr>
              </thead>
              <tbody>
                {isGold ? (
                  <>
                    <tr className="border-t border-[var(--color-border)]/60">
                      <td className="py-2"><StratTag color={STRAT_COLOR.alpha} label="Alpha-Sweep" /></td>
                      <td className="py-2 text-right num">4%</td>
                      <td className="py-2 text-right num">100 oz</td>
                    </tr>
                    <tr className="border-t border-[var(--color-border)]/60">
                      <td className="py-2"><StratTag color={STRAT_COLOR.meanrev} label="Mean-Rev" /></td>
                      <td className="py-2 text-right num">3%</td>
                      <td className="py-2 text-right num">100 oz</td>
                    </tr>
                    <tr className="border-t border-[var(--color-border)]/60">
                      <td className="py-2"><StratTag color={STRAT_COLOR.cross} label="Cross-Market" /></td>
                      <td className="py-2 text-right num">2%</td>
                      <td className="py-2 text-right num">100 oz</td>
                    </tr>
                  </>
                ) : (
                  <tr className="border-t border-[var(--color-border)]/60">
                    <td className="py-2"><StratTag color={STRAT_COLOR.alpha} label="Alpha-Sweep" /></td>
                    <td className="py-2 text-right num">4%</td>
                    <td className="py-2 text-right num">5,000 barrels</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Alpha-Sweep Params */}
        <Card className="hom-stagger" lift>
          <Card.Header>
            <Card.Title>
              <span style={{ color: STRAT_COLOR.alpha }}>Alpha-Sweep</span>
              <span className="text-[var(--color-text-muted)] font-normal ml-2">{symbol}</span>
            </Card.Title>
          </Card.Header>
          <div className="px-4 pb-4 flex flex-col gap-1.5">
            <Row label="Asia min range" value={isGold ? "$5.00" : "$0.50"} />
            <Row label="Sweep threshold" value={isGold ? "$2.00" : "$0.20"} />
            <Row label="SL buffer" value={isGold ? "$0.30" : "$0.03"} />
            <Row label="Min SL distance" value={isGold ? "$5.00" : "$0.10"} />
            <Row label="TP multiplier" value="2.0x Asia range" />
            <Row label="Break-even trigger" value="50% to TP" />
            <Row label="Max hold" value="80 bars (~4h)" />
            <Row label="Skip first bar" value={<Badge tone="win" variant="soft">Yes</Badge>} />
          </div>
        </Card>

        {/* Gold-only strategies */}
        {isGold ? (
          <>
            <Card className="hom-stagger" lift>
              <Card.Header>
                <Card.Title>
                  <span style={{ color: STRAT_COLOR.meanrev }}>Mean-Rev</span>
                </Card.Title>
              </Card.Header>
              <div className="px-4 pb-4 flex flex-col gap-1.5">
                <Row label="Condition 1 threshold" value="-0.4" />
                <Row label="Condition 2 threshold" value="-0.8" />
                <Row label="SL range multiplier" value="1.0x avg 10d range" />
                <Row label="Max hold" value="5 days" />
                <Row label="Direction" value="Long only" />
              </div>
            </Card>

            <Card className="hom-stagger" lift>
              <Card.Header>
                <Card.Title>
                  <span style={{ color: STRAT_COLOR.cross }}>Cross-Market</span>
                </Card.Title>
              </Card.Header>
              <div className="px-4 pb-4 flex flex-col gap-1.5">
                <Row label="Consensus threshold" value="0.30" />
                <Row label="Return threshold" value="0.5%" />
                <Row label="SL" value="2x ATR(14)" />
                <Row label="TP" value="4x ATR(14)" />
                <Row label="Max hold" value="20 days" />
                <Row label="Direction" value="Long only" />
                <Row label="Weights" value="EUR:2 US10Y:3 SPX:1 Ag:2 Oil:1 US2Y:2" />
              </div>
            </Card>
          </>
        ) : null}

        {/* DD Protection */}
        <Card className="hom-stagger" lift>
          <Card.Header>
            <Card.Title>DD Protection</Card.Title>
          </Card.Header>
          <div className="px-4 pb-4 flex flex-col gap-1.5">
            {isGold ? (
              <Row label="50-MA filter" value="Blocks Mean-Rev + Cross longs below MA" />
            ) : null}
            <Row label="Halve size after" value="3 consecutive losses" />
            <Row label="Pause signals after" value="5 consecutive losses (skip 2)" />
            <Row label="Equity MA period" value="20 trades" />
            <Row label="Max hold kill" value="80 bars (position monitor)" />
          </div>
        </Card>

        {/* OANDA */}
        <Card className="hom-stagger" lift>
          <Card.Header>
            <Card.Title>OANDA Connection</Card.Title>
            <Badge tone="win" variant="soft">Live · demo</Badge>
          </Card.Header>
          <div className="px-4 pb-4 flex flex-col gap-1.5">
            <Row label="Account" value="101-004-39331014-001" />
            <Row label="Type" value="Practice (Demo)" />
            <Row label="Instrument" value={isGold ? "XAU_USD" : "BCO_USD"} />
            <Row label="Backend port" value={isGold ? "5053" : "5054"} />
          </div>
        </Card>
      </div>
    </div>
  );
}

function StratTag({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium" style={{ color }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}
