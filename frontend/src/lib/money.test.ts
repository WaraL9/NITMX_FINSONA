import { describe, expect, it } from "vitest";
import { formatMillions, formatTHB } from "./money";

describe("formatTHB", () => {
  it.each([
    ["5000000.00", "5,000,000.00"],
    ["450000", "450,000.00"],
    ["-3800000.00", "-3,800,000.00"],
    ["0.5", "0.50"],
    ["999.00", "999.00"],
  ])("%s -> %s", (input, out) => expect(formatTHB(input)).toBe(out));

  it("rounds half-up without decimals", () => {
    expect(formatTHB("3499999.50", 0)).toBe("3,500,000");
    expect(formatTHB("3499999.49", 0)).toBe("3,499,999");
  });

  it("keeps precision beyond float range", () => {
    expect(formatTHB("90071992547409931.23")).toBe("90,071,992,547,409,931.23");
  });

  it("rejects garbage", () => {
    expect(() => formatTHB("1,000")).toThrow();
  });
});

describe("formatMillions", () => {
  it.each([
    ["32000000.00", "32.0 ลบ."],
    ["-3800000.00", "-3.8 ลบ."],
    ["3679584.00", "3.7 ลบ."],
    ["450000.00", "0.5 ลบ."],
  ])("%s -> %s", (input, out) => expect(formatMillions(input)).toBe(out));

  it("supports two digits", () => {
    expect(formatMillions("3679584.00", 2)).toBe("3.68 ลบ.");
  });
});
