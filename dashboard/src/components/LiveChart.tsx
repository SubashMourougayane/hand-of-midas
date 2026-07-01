// TradingView SAVED LAYOUT iframe embed.
//
// Uses your saved chart layout (`kcFgtken`) so all settings — countdown,
// indicators, drawings, timezone — persist across reloads. The widgetembed
// URL accepts a `chart` param pointing to a public layout ID.
//
// If you change layouts, update LAYOUT_ID. The layout must be public/sharable
// on your TradingView account (lock icon → "Make it public").
export function LiveChart({
  symbol = "OANDA:XAUUSD",
  interval = "15",
  height = 460,
}: {
  symbol?: string;
  interval?: string;
  height?: number;
}) {
  const LAYOUT_ID = "kcFgtken";
  const params = new URLSearchParams({
    symbol,
    interval,
    timezone: "Etc/UTC",
    theme: "dark",
    style: "1",
    locale: "en",
    enable_publishing: "false",
    hide_side_toolbar: "false",
    allow_symbol_change: "true",
    save_image: "false",
    chart: LAYOUT_ID,
    backgroundColor: "rgba(14, 20, 25, 1)",
    gridColor: "rgba(43, 52, 65, 0.6)",
  });

  const src = `https://s.tradingview.com/widgetembed/?${params.toString()}`;

  return (
    <iframe
      src={src}
      title="XAUUSD M15"
      style={{ width: "100%", height, border: 0, background: "#0E1419" }}
      allow="clipboard-read; clipboard-write"
      loading="lazy"
    />
  );
}
