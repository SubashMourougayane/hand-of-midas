"use client";
import Sidebar from "@/components/Sidebar";
import { useInstrument } from "@/lib/instrument";

export default function SettingsPage() {
  const { instrument } = useInstrument();

  return (
    <>
      <Sidebar />
      <main className="flex-1 p-6 overflow-auto">
        <h1 className="text-xl font-bold text-[var(--text)] mb-1">SETTINGS</h1>
        <p className="text-xs text-[var(--text-dim)] mb-5">
          {instrument === "gold" ? "GoldDigger" : "OilMiner"} — Strategy parameters and execution configuration
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

          {/* Strategy Risk */}
          <div className="t-panel p-4">
            <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">Risk Allocation</h2>
            <table className="w-full text-xs">
              <thead><tr className="text-[var(--text-dim)]"><th className="text-left py-1">Strategy</th><th className="text-right">Risk %</th><th className="text-right">Max Position</th></tr></thead>
              <tbody>
                {instrument === "gold" ? (
                  <>
                    <tr className="border-t border-[var(--border)]"><td className="py-1.5 text-[#4fc3f7]">Alpha-Sweep</td><td className="text-right">4%</td><td className="text-right">100 oz</td></tr>
                    <tr className="border-t border-[var(--border)]"><td className="py-1.5 text-[#00e87b]">Mean-Rev</td><td className="text-right">3%</td><td className="text-right">100 oz</td></tr>
                    <tr className="border-t border-[var(--border)]"><td className="py-1.5 text-[#ffd54f]">Cross-Market</td><td className="text-right">2%</td><td className="text-right">100 oz</td></tr>
                  </>
                ) : (
                  <tr className="border-t border-[var(--border)]"><td className="py-1.5 text-[#4fc3f7]">Alpha-Sweep</td><td className="text-right">4%</td><td className="text-right">5,000 barrels</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Alpha-Sweep Params */}
          <div className="t-panel p-4">
            <h2 className="text-xs font-semibold text-[#4fc3f7] uppercase mb-3">Alpha-Sweep ({instrument === "gold" ? "XAU/USD" : "BCO/USD"})</h2>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Asia min range</span><span>{instrument === "gold" ? "$5.00" : "$0.50"}</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Sweep threshold</span><span>{instrument === "gold" ? "$2.00" : "$0.20"}</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">SL buffer</span><span>{instrument === "gold" ? "$0.30" : "$0.03"}</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Min SL distance</span><span>{instrument === "gold" ? "$5.00" : "$0.10"}</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">TP multiplier</span><span>2.0x Asia range</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Break-even trigger</span><span>50% to TP</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Max hold</span><span>80 bars (~4h)</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Skip first bar</span><span className="text-[var(--green)]">Yes</span></div>
            </div>
          </div>

          {/* Gold-only strategies */}
          {instrument === "gold" && (
            <>
              <div className="t-panel p-4">
                <h2 className="text-xs font-semibold text-[#00e87b] uppercase mb-3">Mean-Rev</h2>
                <div className="space-y-1.5 text-xs">
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Condition 1 threshold</span><span>-0.4</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Condition 2 threshold</span><span>-0.8</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">SL range multiplier</span><span>1.0x avg 10d range</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Max hold</span><span>5 days</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Direction</span><span>Long only</span></div>
                </div>
              </div>

              <div className="t-panel p-4">
                <h2 className="text-xs font-semibold text-[#ffd54f] uppercase mb-3">Cross-Market</h2>
                <div className="space-y-1.5 text-xs">
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Consensus threshold</span><span>0.30</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Return threshold</span><span>0.5%</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">SL</span><span>2x ATR(14)</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">TP</span><span>4x ATR(14)</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Max hold</span><span>20 days</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Direction</span><span>Long only</span></div>
                  <div className="flex justify-between"><span className="text-[var(--text-dim)]">Weights</span><span>EUR:2 US10Y:3 SPX:1 Ag:2 Oil:1 US2Y:2</span></div>
                </div>
              </div>
            </>
          )}

          {/* DD Protection */}
          <div className="t-panel p-4">
            <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">DD Protection</h2>
            <div className="space-y-1.5 text-xs">
              {instrument === "gold" && (
                <div className="flex justify-between"><span className="text-[var(--text-dim)]">50-MA filter</span><span>Blocks Mean-Rev + Cross longs below MA</span></div>
              )}
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Halve size after</span><span>3 consecutive losses</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Pause signals after</span><span>5 consecutive losses (skip 2)</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Equity MA period</span><span>20 trades</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Max hold kill</span><span>80 bars (position monitor)</span></div>
            </div>
          </div>

          {/* OANDA */}
          <div className="t-panel p-4">
            <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">OANDA Connection</h2>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Account</span><span>101-004-39331014-001</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Type</span><span>Practice (Demo)</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Instrument</span><span>{instrument === "gold" ? "XAU_USD" : "BCO_USD"}</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Backend port</span><span>{instrument === "gold" ? "5053" : "5054"}</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-dim)]">Execution mode</span><span className="text-[var(--green)] font-semibold">LIVE (demo)</span></div>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
