import { describe, expect, it } from "vitest";
import { fmtAge, fmtCompact, fmtPct, fmtPrice, fmtSigned, tone } from "../format";

describe("number formatting", () => {
  it("shows prices with precision that fits their size", () => {
    expect(fmtPrice(1.12145)).toBe("1.1215");
    expect(fmtPrice(262.054)).toBe("262.05");
    expect(fmtPrice(null)).toBe("—");
  });
  it("signs changes with a typographic minus", () => {
    expect(fmtSigned(1.5)).toBe("+1.50");
    expect(fmtSigned(-1.5)).toBe("−1.50");
    expect(fmtPct(-0.25)).toBe("−0.25%");
  });
  it("abbreviates large amounts", () => {
    expect(fmtCompact(21_540_000_000)).toBe("21.54B");
    expect(fmtCompact(-1_500_000)).toBe("−1.5M");
  });
  it("colors by direction", () => {
    expect(tone(1)).toBe("text-up");
    expect(tone(-1)).toBe("text-down");
    expect(tone(0)).toBe("text-dim");
  });
  it("describes data age", () => {
    const now = new Date("2026-11-15T12:00:00Z");
    expect(fmtAge("2026-11-15T11:30:00Z", now)).toBe("30 min ago");
    expect(fmtAge("2026-11-12T12:00:00Z", now)).toBe("3 d ago");
  });
});
