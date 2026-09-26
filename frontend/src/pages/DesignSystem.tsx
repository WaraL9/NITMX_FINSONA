import { CheckCircle2, MessageSquareMore, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, SourceBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Modal } from "@/components/ui/modal";
import { Slider } from "@/components/ui/slider";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Toggle } from "@/components/ui/toggle";
import { useTheme } from "@/lib/theme";

const swatches = [
  "canvas", "panel", "surface", "surface-2", "line", "ink", "body", "muted",
  "verified", "tax", "judge", "navy", "risk",
] as const;

/** Reads the token's current value, so the gallery reflects the active theme. */
function useTokenValues(theme: string) {
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    const cs = getComputedStyle(document.documentElement);
    setValues(Object.fromEntries(swatches.map((n) => [n, cs.getPropertyValue(`--color-${n}`).trim()])));
  }, [theme]);
  return values;
}

/** Living style guide for E0-04. Every UI primitive in one place. */
export default function DesignSystem() {
  const [open, setOpen] = useState(false);
  const [household, setHousehold] = useState(true);
  const [amount, setAmount] = useState(5.0);
  const { theme, setTheme } = useTheme();
  const tokens = useTokenValues(theme);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Design system</h1>
        <p className="mt-1 text-sm text-muted">Enterprise Functional Minimalism · ตัวอักษร IBM Plex Sans Thai</p>
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant={theme === "dim" ? "primary" : "secondary"} onClick={() => setTheme("dim")}>
            Dim
          </Button>
          <Button size="sm" variant={theme === "light" ? "primary" : "secondary"} onClick={() => setTheme("light")}>
            Light
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader title="สี (Tokens)" />
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
          {swatches.map((name) => (
            <div key={name} className="text-xs">
              <div className="h-12 rounded-md border border-line" style={{ background: `var(--color-${name})` }} />
              <div className="mt-1 font-medium text-ink">{name}</div>
              <div className="font-mono text-muted">{tokens[name]}</div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="ปุ่ม (Buttons)" />
          <div className="flex flex-wrap gap-2">
            <Button>ส่งออกรายงาน Credit Memo</Button>
            <Button variant="verified">
              <CheckCircle2 className="size-4" /> Accept as Operating
            </Button>
            <Button variant="secondary">
              <XCircle className="size-4" /> Keep Non-Operating
            </Button>
            <Button variant="ghost">
              <MessageSquareMore className="size-4" /> Query RM
            </Button>
            <Button variant="danger">ลบ</Button>
            <Button disabled>Disabled</Button>
          </div>
        </Card>

        <Card>
          <CardHeader title="ป้ายสถานะ (Badges)" />
          <div className="flex flex-wrap gap-2">
            <Badge tone="verified">PromptBiz Certified</Badge>
            <Badge tone="tax">Tax-Verified ภ.พ.30</Badge>
            <Badge tone="judge">Human Action Required</Badge>
            <Badge tone="risk">DSCR 1.05 ต่ำกว่าเกณฑ์</Badge>
            <Badge tone="navy">CA Override</Badge>
            <Badge>Neutral</Badge>
            <SourceBadge mode="live" source="Statement PDF" />
            <SourceBadge mode="sandbox" source="PromptBiz" />
          </div>
        </Card>

        <Card accent="verified">
          <CardHeader title="ระดับที่ 1: Golden Inflow" subtitle="การ์ด accent" />
          <div className="num font-mono text-3xl font-semibold text-verified">15,000,000</div>
          <div className="text-xs text-muted">บาท · 60% ของรายได้</div>
        </Card>

        <Card accent="judge">
          <CardHeader title="ระดับที่ 4: Unverified Inflow" />
          <div className="num font-mono text-3xl font-semibold text-judge">2,000,000</div>
          <div className="text-xs text-muted">บาท · 3 รายการใน Watchlist</div>
        </Card>

        <Card>
          <CardHeader title="สวิตช์ & แถบเลื่อน" />
          <div className="space-y-6">
            <Toggle checked={household} onChange={setHousehold} label="แยกเงินกงสีครัวเรือนออก" />
            <div>
              <div className="flex justify-between text-sm">
                <span>วงเงินจำลอง</span>
                <span className="num font-mono font-semibold text-ink">{amount.toFixed(1)} ลบ.</span>
              </div>
              <Slider
                min={1}
                max={5}
                step={0.1}
                value={amount}
                onChange={setAmount}
                marker={{ value: 3.5, label: "Safe 3.5" }}
                aria-label="วงเงินจำลอง"
              />
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="Modal" />
          <Button variant="secondary" onClick={() => setOpen(true)}>
            เปิดผังเส้นทางเงินวน
          </Button>
          <Modal
            open={open}
            onClose={() => setOpen(false)}
            title="ผังเส้นทางเงินวน (Loop B)"
            footer={<Button onClick={() => setOpen(false)}>ปิด</Button>}
          >
            <p className="text-sm">BBL → KBANK → บัญชีกรรมการ → BBL · 500,000 → 495,000 → 490,000 ภายใน 48 ชม.</p>
          </Modal>
        </Card>
      </div>

      <Card>
        <CardHeader title="ตาราง (Table)" />
        <Table>
          <THead>
            <tr>
              <TH>วันที่</TH>
              <TH>คู่โอน</TH>
              <TH className="text-right">ยอดเงิน</TH>
              <TH>สถานะ</TH>
            </tr>
          </THead>
          <TBody>
            <TR>
              <TD>08/03/2026</TD>
              <TD>บจก. เอ บิลด์</TD>
              <TD numeric>450,000.00</TD>
              <TD>
                <Badge tone="judge">รอดุลยพินิจ</Badge>
              </TD>
            </TR>
            <TR>
              <TD>19/02/2026</TD>
              <TD>นางสาวพิมพ์ชนก ใจดี</TD>
              <TD numeric>850,000.00</TD>
              <TD>
                <Badge tone="judge">รอดุลยพินิจ</Badge>
              </TD>
            </TR>
          </TBody>
        </Table>
      </Card>
    </div>
  );
}
