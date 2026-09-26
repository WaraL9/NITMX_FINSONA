import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, Search } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api, documentFileUrl, unwrap, type Account } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ownerType, tagLabel, tierInfo } from "@/lib/labels";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function formatDateTime(iso: string) {
  // "2026-03-08T11:05:00" -> "08/03/2026 11:05" (no timezone conversion; statement local time)
  const [d, t] = iso.split("T");
  const [y, m, day] = d.split("-");
  return `${day}/${m}/${y} ${t.slice(0, 5)}`;
}

export function TransactionsPanel({ caseId, accounts }: { caseId: number; accounts: Account[] }) {
  const [accountId, setAccountId] = useState<number | undefined>();
  const [tier, setTier] = useState<string | undefined>();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const q = useDebounced(search.trim());

  useEffect(() => setPage(0), [accountId, q, tier]);

  const { data, isFetching, isError } = useQuery({
    queryKey: ["transactions", caseId, accountId, q, tier, page],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/cases/{case_id}/transactions", {
          params: {
            path: { case_id: caseId },
            query: { account_id: accountId, q: q || undefined, tier, offset: page * PAGE_SIZE, limit: PAGE_SIZE },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });

  const byId = new Map(accounts.map((a) => [a.id, a]));
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <Card>
      <CardHeader
        title="รายการธุรกรรมที่สกัดได้"
        subtitle="ทุกบรรทัดผูกกับหน้าและพิกัดบนเอกสารต้นฉบับ · คลิกเพื่อเปิดหน้าเอกสาร"
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-60 flex-1">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ค้นหารายละเอียด / คู่โอน เช่น งานตกแต่งคลินิก"
            className="h-9 w-full rounded-md border border-line bg-surface pr-3 pl-9 text-sm text-ink outline-none focus:border-navy"
          />
        </div>
        <div className="flex flex-wrap gap-1">
          <FilterChip active={accountId === undefined} onClick={() => setAccountId(undefined)}>
            ทุกบัญชี
          </FilterChip>
          {accounts.map((a) => (
            <FilterChip key={a.id} active={accountId === a.id} onClick={() => setAccountId(a.id)}>
              {a.bank_code} ·{a.account_no_masked.slice(-6, -2)}
              {a.owner_type !== "company" && <span className="text-judge"> ({ownerType[a.owner_type]})</span>}
            </FilterChip>
          ))}
        </div>
      </div>

      {isError && <p className="mb-4 text-sm text-risk">โหลดรายการธุรกรรมไม่สำเร็จ — ตรวจสอบว่า backend ทำงานอยู่</p>}
      <div className="mb-4 flex flex-wrap gap-1">
        <FilterChip active={tier === undefined} onClick={() => setTier(undefined)}>
          ทุกระดับ
        </FilterChip>
        {Object.entries(tierInfo).map(([k, v]) => (
          <FilterChip key={k} active={tier === k} onClick={() => setTier(k)}>
            {v.short}
          </FilterChip>
        ))}
      </div>

      <div className={cn("transition-opacity", isFetching && "opacity-60")}>
        <Table>
          <THead>
            <tr>
              <TH>วันที่ เวลา</TH>
              <TH>บัญชี</TH>
              <TH>รายการ</TH>
              <TH>รายละเอียด</TH>
              <TH>ผลวิเคราะห์</TH>
              <TH className="text-right">ถอน</TH>
              <TH className="text-right">ฝาก</TH>
              <TH className="text-right">คงเหลือ</TH>
              <TH className="text-right">หน้า</TH>
            </tr>
          </THead>
          <TBody>
            {data?.items.map((t) => {
              const a = byId.get(t.account_id);
              return (
                <TR
                  key={t.id}
                  className="cursor-pointer"
                  onClick={() => t.document_id && window.open(documentFileUrl(t.document_id, t.page_no), "_blank")}
                  title="เปิดหน้าเอกสารต้นฉบับ"
                >
                  <TD className="font-mono text-xs whitespace-nowrap">{formatDateTime(t.posted_at)}</TD>
                  <TD className="text-xs whitespace-nowrap">
                    {a?.bank_code} <span className="font-mono text-muted">{a?.account_no_masked.slice(-6, -2)}</span>
                  </TD>
                  <TD className="font-mono text-xs">{t.code}</TD>
                  <TD className="max-w-md">
                    <div className="truncate text-ink" title={t.description}>
                      {t.counterparty_name ?? t.description}
                    </div>
                    {t.counterparty_name && (
                      <div className="truncate text-xs text-muted" title={t.description}>
                        {t.description}
                      </div>
                    )}
                  </TD>
                  <TD className="max-w-56" title={t.tag_reason ?? undefined}>
                    <div className="flex flex-wrap gap-1">
                      {t.tier && <Badge tone={tierInfo[t.tier]?.tone}>{tierInfo[t.tier]?.short}</Badge>}
                      {t.loop_id && <Badge tone="risk">{t.loop_id}</Badge>}
                      {t.tag && !t.tier && <Badge>{tagLabel[t.tag] ?? t.tag}</Badge>}
                    </div>
                  </TD>
                  <TD numeric className="text-risk">
                    {t.debit !== "0.00" ? formatTHB(t.debit) : ""}
                  </TD>
                  <TD numeric className="text-verified">
                    {t.credit !== "0.00" ? formatTHB(t.credit) : ""}
                  </TD>
                  <TD numeric>{t.balance ? formatTHB(t.balance) : ""}</TD>
                  <TD numeric className="text-muted">
                    <span className="inline-flex items-center gap-1">
                      {t.page_no} <ExternalLink className="size-3" />
                    </span>
                  </TD>
                </TR>
              );
            })}
            {data && data.items.length === 0 && (
              <tr>
                <TD colSpan={9} className="py-8 text-center text-muted">
                  ไม่พบรายการ
                </TD>
              </tr>
            )}
          </TBody>
        </Table>
      </div>

      {data && (
        <div className="mt-3 flex items-center justify-between text-sm text-muted">
          <span>
            {data.total.toLocaleString()} รายการ · หน้า {page + 1} / {pages}
          </span>
          <div className="flex gap-1">
            <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={page + 1 >= pages}
              onClick={() => setPage((p) => p + 1)}
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "h-8 rounded-full border px-3 text-xs whitespace-nowrap transition-colors",
        active ? "border-navy bg-navy text-white" : "border-line bg-panel text-body hover:bg-surface-2",
      )}
    >
      {children}
    </button>
  );
}
