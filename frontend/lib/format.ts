const USD_INR = 96.82;

/**
 * Format number in Indian comma style: 1,00,00,000
 */
export function formatINR(amount: number): string {
  const inr = Math.round(amount * USD_INR);
  const isNeg = inr < 0;
  const abs = Math.abs(inr);
  const str = abs.toString();

  if (str.length <= 3) return (isNeg ? "-" : "") + "₹" + str;

  // Indian format: last 3 digits, then groups of 2
  const last3 = str.slice(-3);
  const rest = str.slice(0, -3);
  const grouped = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",");

  return (isNeg ? "-" : "") + "₹" + grouped + "," + last3;
}

/**
 * Format USD with optional INR beside it: $1,234 (₹1,19,512)
 */
export function formatUSDwithINR(usd: number, opts?: { compact?: boolean; sign?: boolean }): string {
  const sign = opts?.sign && usd > 0 ? "+" : "";
  const usdStr = `${sign}$${Math.abs(usd).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const inrStr = formatINR(usd);

  if (opts?.compact) {
    return `${usd < 0 ? "-" : ""}${usdStr} (${inrStr})`;
  }
  return `${usd < 0 ? "-" : sign}${usdStr} (${inrStr})`;
}

/**
 * Just the INR part for when you need it separately.
 */
export function usdToINR(usd: number): number {
  return usd * USD_INR;
}

export { USD_INR };
