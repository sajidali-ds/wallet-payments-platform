// Money is an integer number of paise everywhere (the backend never uses floats either).
// The only place a decimal appears is the text the user types, and we parse that as TEXT,
// never through parseFloat, so 0.1 + 0.2 style rounding errors cannot happen.

export const MAX_AMOUNT_PAISE = 10_000_000_000; // same cap as the wallet-service

export type ParsedAmount = { ok: true; paise: number } | { ok: false; reason: string };

export function parseRupees(input: string): ParsedAmount {
  const text = input.trim().replace(/,/g, "");
  if (text === "") return { ok: false, reason: "Enter an amount." };
  if (!/^\d+(\.\d{1,2})?$/.test(text)) {
    return { ok: false, reason: "Use digits with at most 2 decimals, like 1200 or 1200.50." };
  }
  const [whole, fraction = ""] = text.split(".");
  if (whole.replace(/^0+/, "").length > 9) {
    return { ok: false, reason: `The maximum is ${formatPaise(MAX_AMOUNT_PAISE)}.` };
  }
  const paise = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (paise <= 0) return { ok: false, reason: "The amount must be more than ₹0." };
  if (paise > MAX_AMOUNT_PAISE) {
    return { ok: false, reason: `The maximum is ${formatPaise(MAX_AMOUNT_PAISE)}.` };
  }
  return { ok: true, paise };
}

const indianGrouping = new Intl.NumberFormat("en-IN");

export function formatPaise(paise: number, options: { showSign?: boolean } = {}): string {
  const abs = Math.abs(paise);
  const rupees = Math.floor(abs / 100);
  const remainder = String(abs % 100).padStart(2, "0");
  const body = `₹${indianGrouping.format(rupees)}.${remainder}`;
  if (paise < 0) return `−${body}`; // a real minus sign, not a hyphen
  if (options.showSign && paise > 0) return `+${body}`;
  return body;
}
