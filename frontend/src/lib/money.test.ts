import { describe, expect, it } from "vitest";
import { MAX_AMOUNT_PAISE, formatPaise, parseRupees } from "./money";

describe("parseRupees", () => {
  it("converts rupees text to integer paise without floats", () => {
    expect(parseRupees("1200")).toEqual({ ok: true, paise: 120000 });
    expect(parseRupees("1200.5")).toEqual({ ok: true, paise: 120050 });
    expect(parseRupees("0.07")).toEqual({ ok: true, paise: 7 });
    expect(parseRupees(" 1,50,000.25 ")).toEqual({ ok: true, paise: 15000025 });
  });

  it("is exact where floating point is not (0.1 + 0.2 style amounts)", () => {
    expect(parseRupees("0.29")).toEqual({ ok: true, paise: 29 }); // 0.29 * 100 === 28.999999999999996
    expect(parseRupees("1.15")).toEqual({ ok: true, paise: 115 }); // 1.15 * 100 === 114.99999999999999
  });

  it("rejects empty, zero, negative, too precise and non-numeric input", () => {
    for (const bad of ["", "   ", "0", "0.00", "-5", "1.234", "abc", "1e3", "1.", ".5"]) {
      expect(parseRupees(bad).ok).toBe(false);
    }
  });

  it("enforces the same maximum as the wallet-service", () => {
    expect(parseRupees("100000000")).toEqual({ ok: true, paise: MAX_AMOUNT_PAISE });
    expect(parseRupees("100000000.01").ok).toBe(false);
    expect(parseRupees("99999999999999999999").ok).toBe(false);
  });
});

describe("formatPaise", () => {
  it("formats with Indian digit grouping and two decimals", () => {
    expect(formatPaise(0)).toBe("₹0.00");
    expect(formatPaise(7)).toBe("₹0.07");
    expect(formatPaise(120000)).toBe("₹1,200.00");
    expect(formatPaise(15000025)).toBe("₹1,50,000.25");
  });

  it("shows explicit signs for ledger entries", () => {
    expect(formatPaise(-120000, { showSign: true })).toBe("−₹1,200.00");
    expect(formatPaise(120000, { showSign: true })).toBe("+₹1,200.00");
    expect(formatPaise(120000)).toBe("₹1,200.00");
  });
});
