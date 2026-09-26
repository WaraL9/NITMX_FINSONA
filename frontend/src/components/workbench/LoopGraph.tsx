import {
  Background,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  useNodesInitialized,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Landmark, Repeat, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Account, Analysis } from "@/api/client";
import { useLineage } from "@/components/lineage/LineageDrawer";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Modal } from "@/components/ui/modal";
import { ownerType } from "@/lib/labels";
import { formatTHB } from "@/lib/money";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const LOOP_COLORS = ["#f87171", "#fb923c", "#f472b6", "#facc15", "#a78bfa"];

type AccountNodeData = { account: Account; involved: boolean };

function AccountNode({ data }: NodeProps<Node<AccountNodeData>>) {
  const a = data.account;
  const Icon = a.owner_type === "company" ? Landmark : UserRound;
  return (
    <div
      className={cn(
        "w-44 rounded-lg border bg-panel px-3 py-2 text-left shadow-sm transition-opacity",
        a.owner_type === "company" ? "border-tax/50" : "border-judge/60",
        !data.involved && "opacity-40",
      )}
    >
      {/* Handles on all sides so edges can leave/enter from whichever side is shortest. */}
      {(["Top", "Right", "Bottom", "Left"] as const).map((side) => (
        <span key={side}>
          <Handle type="source" id={`s-${side}`} position={Position[side]} className="!opacity-0" />
          <Handle type="target" id={`t-${side}`} position={Position[side]} className="!opacity-0" />
        </span>
      ))}
      <div className="flex items-center gap-2 text-sm font-semibold text-ink">
        <Icon className={cn("size-4", a.owner_type === "company" ? "text-tax" : "text-judge")} />
        {a.bank_code} <span className="font-mono text-xs font-normal text-muted">{a.account_no_masked.slice(-6, -2)}</span>
      </div>
      <div className="truncate text-[11px] text-body">{a.account_name}</div>
      <div className={cn("text-[10px]", a.owner_type === "company" ? "text-tax" : "text-judge")}>{ownerType[a.owner_type]}</div>
    </div>
  );
}

const nodeTypes = { account: AccountNode };

function side(dx: number, dy: number): "Top" | "Right" | "Bottom" | "Left" {
  return Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "Right" : "Left") : dy > 0 ? "Bottom" : "Top";
}

function fmtTime(iso: string) {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)} ${iso.slice(11, 16)}`;
}

function FitOnChange({ dep }: { dep: unknown }) {
  // Re-fit once nodes are measured and whenever the selected loop changes.
  const { fitView } = useReactFlow();
  const measured = useNodesInitialized();
  useEffect(() => {
    if (measured) void fitView({ padding: 0.25, duration: 300 });
  }, [measured, dep, fitView]);
  return null;
}

function Graph({ a, accounts, selected, onLeg }: { a: Analysis; accounts: Account[]; selected: string | null; onLeg: (creditTxnId: number) => void }) {
  const { theme } = useTheme();
  const { nodes, edges } = useMemo(() => {
    const loops = a.loops.filter((l) => !selected || l.id === selected);
    const involved = new Set(loops.flatMap((l) => l.legs.flatMap((g) => [g.from_account_id, g.to_account_id])));
    const r = 210;
    const pos = new Map(
      accounts.map((acc, i) => {
        const ang = (i / accounts.length) * 2 * Math.PI - Math.PI / 2;
        return [acc.id, { x: Math.cos(ang) * r * 1.45, y: Math.sin(ang) * r }];
      }),
    );
    const nodes: Node<AccountNodeData>[] = accounts.map((acc) => ({
      id: String(acc.id),
      type: "account",
      position: pos.get(acc.id)!,
      data: { account: acc, involved: involved.has(acc.id) },
      draggable: true,
    }));
    const edges: Edge[] = loops.flatMap((l) => {
      const color = LOOP_COLORS[a.loops.indexOf(l) % LOOP_COLORS.length];
      return l.legs.map((g, i) => {
        const p1 = pos.get(g.from_account_id)!;
        const p2 = pos.get(g.to_account_id)!;
        return {
          id: `${l.id}-${i}`,
          source: String(g.from_account_id),
          target: String(g.to_account_id),
          sourceHandle: `s-${side(p2.x - p1.x, p2.y - p1.y)}`,
          targetHandle: `t-${side(p1.x - p2.x, p1.y - p2.y)}`,
          animated: true,
          label: `${l.id}·${i + 1}  ${formatTHB(g.amount, 0)}  ${fmtTime(g.at)}`,
          labelStyle: { fontSize: 11, fontFamily: "IBM Plex Mono", fill: color },
          labelBgStyle: { fill: "var(--color-panel)" },
          labelBgPadding: [6, 3] as [number, number],
          style: { stroke: color, strokeWidth: 2.25 },
          markerEnd: { type: MarkerType.ArrowClosed, color, width: 18, height: 18 },
          data: { credit: g.credit_txn_id },
        };
      });
    });
    return { nodes, edges };
  }, [a, accounts, selected]);

  return (
    <div className="h-[460px] overflow-hidden rounded-lg border border-line">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        colorMode={theme === "dim" ? "dark" : "light"}
        proOptions={{ hideAttribution: true }}
        onEdgeClick={(_, e) => onLeg((e.data as { credit: number }).credit)}
        nodesConnectable={false}
        style={{ background: "var(--color-surface)" }}
      >
        <Background gap={24} />
        <FitOnChange dep={selected} />
      </ReactFlow>
    </div>
  );
}

/** E8-07: detected circular flows as a graph (overview card + full-screen modal). */
export function LoopsCard({ caseId, a, accounts }: { caseId: number; a: Analysis; accounts: Account[] }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const { openTxn, openLoop } = useLineage();
  const label = (id: string) => accounts.find((x) => x.id === Number(id));

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Repeat className="size-4 text-risk" /> เงินโอนวนที่ตรวจพบ ({a.loops.length})
          </span>
        }
        subtitle="ตรวจจับด้วยกราฟธุรกรรมตามเวลา · ตัดยอดออกจากรายได้โดยอัตโนมัติ"
        action={
          <Button size="sm" variant="secondary" data-testid="open-loop-graph" onClick={() => setOpen(true)}>
            ดูผังเส้นทางเงินวน
          </Button>
        }
      />
      <div className="space-y-2">
        {a.loops.map((l, i) => (
          <button
            key={l.id}
            onClick={() => openLoop(caseId, l.id, `วงจร ${l.id} · ${l.legs.length} ทอด`)}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-left text-sm hover:border-risk/60"
          >
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 font-medium text-ink">
                <span className="size-2.5 rounded-full" style={{ background: LOOP_COLORS[i % LOOP_COLORS.length] }} />
                {l.id} · {l.legs.length} ทอด · {l.hours} ชม.
              </span>
              <span className="num font-mono text-risk">−{formatTHB(l.netted_amount, 0)}</span>
            </div>
            <div className="mt-0.5 truncate font-mono text-[11px] text-muted">
              {l.legs.map((g) => { const x = label(String(g.from_account_id)); return `${x?.bank_code}·${x?.account_no_masked.slice(-6, -2)}`; }).join(" → ")}
              {" → ↺"}
            </div>
          </button>
        ))}
        {a.loops.length === 0 && <p className="text-sm text-muted">ไม่พบเงินโอนวน</p>}
      </div>

      <Modal open={open} onClose={() => setOpen(false)} size="xl"
        title={<span className="flex items-center gap-2"><Repeat className="size-4 text-risk" /> ผังเส้นทางเงินวนระหว่างบัญชี</span>}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Button size="sm" variant={selected === null ? "primary" : "secondary"} onClick={() => setSelected(null)}>
            ทุกวงจร
          </Button>
          {a.loops.map((l) => (
            <Button key={l.id} size="sm" variant={selected === l.id ? "primary" : "secondary"} onClick={() => setSelected(l.id)}>
              {l.id} · −{formatTHB(l.netted_amount, 0)}
            </Button>
          ))}
          <span className="ml-auto text-xs text-muted">คลิกเส้นลูกศรเพื่อเปิดรายการบนสเตทเมนต์ต้นฉบับ</span>
        </div>
        {/* Mount only while open: React Flow sizes itself on mount, and a closed <dialog> has no size. */}
        {open && (
          <Graph a={a} accounts={accounts} selected={selected}
            onLeg={(id) => { setOpen(false); openTxn(id); }} />
        )}
        <p className="mt-3 text-xs text-muted">
          เงินก้อนเดิมถูกโอนข้ามบัญชีของตนเองแล้ววนกลับภายใน 72 ชั่วโมง ด้วยยอดใกล้เคียงกัน — ระบบนับยอดที่เข้าบัญชีบริษัทในวงจรเป็นยอดหมุนเวียนเทียมและตัดออกจากรายได้
        </p>
      </Modal>
    </Card>
  );
}
