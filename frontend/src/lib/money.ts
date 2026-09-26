/**
 * Display helpers for money that arrives from the API as decimal strings ("5000000.00").
 * The frontend never does money arithmetic; the backend engine is the only calculator.
 */

const MONEY_RE = /^(-?)(\d+)(?:\.(\d+))?$/;

function groupThousands(intPart: string): string {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** "5000000.00" -> "5,000,000.00"; decimals=0 rounds half-up on the string. */
export function formatTHB(value: string, decimals: 0 | 2 = 2): string {
  const m = MONEY_RE.exec(value.trim());
  if (!m) throw new Error(`not a decimal string: ${value}`);
  const [, sign, int, frac = ""] = m;
  if (decimals === 2) {
    const f = (frac + "00").slice(0, 2);
    return `${sign}${groupThousands(int)}.${f}`;
  }
  const roundUp = (frac[0] ?? "0") >= "5";
  const rounded = roundUp ? (BigInt(int) + 1n).toString() : int.replace(/^0+(?=\d)/, "");
  return `${sign && rounded !== "0" ? "-" : ""}${groupThousands(rounded)}`;
}

/** "5000000.00" -> "5.0 ลบ." (ล้านบาท) for compact cards. */
export function formatMillions(value: string, digits = 1): string {
  const m = MONEY_RE.exec(value.trim());
  if (!m) throw new Error(`not a decimal string: ${value}`);
  const [, sign, int, frac = ""] = m;
  // Scale via BigInt on satang to stay exact, then round to `digits`.
  const satang = BigInt(int + (frac + "00").slice(0, 2));
  const unit = 10n ** BigInt(8 - digits); // 1,000,000 THB = 10^8 satang
  const q = (satang + unit / 2n) / unit;
  const s = q.toString().padStart(digits + 1, "0");
  const whole = s.slice(0, s.length - digits);
  const dec = digits ? "." + s.slice(-digits) : "";
  return `${sign}${groupThousands(whole)}${dec} ลบ.`;
}
