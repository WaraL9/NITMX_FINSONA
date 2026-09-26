"""Synthetic multi-bank statement generator (E1-02).

Builds every transaction for a scenario so that the totals in the scenario file hold
EXACTLY, and records a ground-truth label on each row (tier, loop id, owner money,
household spending ...). Output is deterministic for a given seed.

Company-account credits = T1 + T2 + T3 + unverified + owner/family + loop credit legs
Company-account debits  = business costs + household + existing debt + loop debit legs
Director-account rows are personal and never count as company revenue or cost.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.core.money import to_money
from app.scenario import Scenario, ScenarioAccount

D = Decimal
ZERO = D("0.00")

# Ground-truth categories (used by tests and, later, engine evaluation E15).
REVENUE_T1 = "revenue_t1_golden"
REVENUE_T2 = "revenue_t2_tax"
REVENUE_T3 = "revenue_t3_operational"
UNVERIFIED = "unverified"
OWNER_INJECTION = "owner_injection"
LOOP = "own_account_loop"
BUSINESS_COST = "business_cost"
HOUSEHOLD = "household"
DEBT_SERVICE = "debt_service"
DIRECTOR_PERSONAL = "director_personal"

T1_CUSTOMERS = [
    ("บจก. สยามคลินิก กรุ๊ป", "SCB"),
    ("บจก. ริเวอร์ไซด์ เรสซิเดนซ์", "KBANK"),
    ("บจก. กรีนวิลล์ ดีเวลลอปเมนท์", "BBL"),
    ("บจก. บางนา ออฟฟิศ พาร์ค", "KTB"),
    ("บจก. ลุมพินี เฮลท์แคร์", "SCB"),
    ("บจก. นิวไลฟ์ โฮม", "BAY"),
    ("บจก. สุขุมวิท ดีไซน์ สตูดิโอ", "KBANK"),
    ("บจก. เดอะ คอฟฟี่ คลับ", "TTB"),
]
T2_CUSTOMERS = [
    ("หจก. ทองดี การช่าง", "KTB"),
    ("นายวรวิทย์ แสงทอง", "SCB"),
    ("นางสาวอรอุมา พงษ์ไพร", "KBANK"),
    ("หจก. บ้านสวย พร็อพเพอร์ตี้", "BAY"),
    ("นายธนพล อินทรสุข", "BBL"),
    ("ร้าน มุมกาแฟ", "KBANK"),
    ("นางพรทิพย์ วงศ์ใหญ่", "TTB"),
    ("หจก. เจริญยิ่ง รีโนเวท", "SCB"),
]
T3_PAYER_PREFIX = ["นาย", "นาง", "น.ส."]
T3_PAYER_NAMES = ["สมชาย", "มานพ", "สุดา", "ปิยะ", "อารีย์", "กมล", "ศิริพร", "วิชัย", "นภา", "ธีระ", "จันทร์เพ็ญ", "ประเสริฐ"]
SUPPLIERS = [
    ("บจก. ไทยวัสดุ ภัณฑ์", "KBANK"),
    ("บจก. แกรนด์ วู้ด เวิร์ค", "SCB"),
    ("หจก. สีสวย เพ้นท์", "BBL"),
    ("บจก. ไลท์ติ้ง พลัส", "KTB"),
    ("บจก. ยิปซัม โปร", "BAY"),
    ("บจก. กระจก ไทย ซัพพลาย", "SCB"),
    ("บจก. ฮาร์ดแวร์ เซ็นเตอร์", "KBANK"),
    ("หจก. ช่างไม้ พรีเมียม", "TTB"),
    ("บจก. สุขภัณฑ์ ดีไซน์", "BBL"),
    ("บจก. ขนส่ง รวดเร็ว", "KTB"),
]
FAMILY_MEMBER_FIRST = "นางสมศรี"  # + the director's surname (owner/family rule, E4-04)
FAMILY_MEMBER_ACCT = ("BAY", "xxx-x-x6604-x")


@dataclass
class SynthTxn:
    account: str  # scenario account key
    at: datetime
    code: str
    channel: str
    details: str
    category: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    counterparty: str | None = None
    counterparty_bank: str | None = None
    counterparty_account: str | None = None
    loop_id: str | None = None
    balance: Decimal | None = None
    seq: int = 0  # tie-breaker for identical timestamps

    def truth(self) -> dict:
        return {
            "account": self.account,
            "at": self.at.isoformat(),
            "code": self.code,
            "channel": self.channel,
            "details": self.details,
            "debit": f"{self.debit:.2f}",
            "credit": f"{self.credit:.2f}",
            "balance": f"{self.balance:.2f}",
            "category": self.category,
            "counterparty": self.counterparty,
            "counterparty_account": self.counterparty_account,
            "loop_id": self.loop_id,
        }


@dataclass
class GeneratedAccount:
    spec: ScenarioAccount
    opening_balance: Decimal
    rows: list[SynthTxn]


@dataclass
class GeneratedCase:
    scenario: Scenario
    accounts: dict[str, GeneratedAccount]
    seed: int


class _Gen:
    def __init__(self, sc: Scenario, seed: int):
        self.sc = sc
        self.rng = random.Random(seed)
        director = next((a for a in sc.accounts if a.owner_type == "director"), None)
        last = director.account_name.split()[-1] if director and len(director.account_name.split()) >= 2 else "ศรีวงศ์"
        self.family_member = f"{FAMILY_MEMBER_FIRST} {last}"
        self.accounts = {a.key: a for a in sc.accounts}
        self.txns: list[SynthTxn] = []
        self._seq = 0
        self.months = self._months(sc.case.period_start, sc.case.period_end)

    # ---------- helpers ----------
    @staticmethod
    def _months(start: date, end: date) -> list[tuple[int, int]]:
        out, y, m = [], start.year, start.month
        while (y, m) <= (end.year, end.month):
            out.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out

    def _days_in_month(self, y: int, m: int) -> list[date]:
        d = date(y, m, 1)
        out = []
        while d.month == m:
            if d.weekday() < 6:  # Mon-Sat
                out.append(d)
            d += timedelta(days=1)
        return out

    def rand_dt(self, month: tuple[int, int] | None = None, weekdays: set[int] | None = None,
                hours: tuple[int, int] = (8, 18)) -> datetime:
        y, m = month or self.rng.choice(self.months)
        days = [d for d in self._days_in_month(y, m) if weekdays is None or d.weekday() in weekdays]
        d = self.rng.choice(days)
        t = time(self.rng.randint(hours[0], hours[1] - 1), self.rng.randint(0, 59))
        return datetime.combine(d, t)

    def split_exact(self, total: Decimal, n: int, spread: tuple[float, float] = (0.4, 1.6),
                    quantum: Decimal = D("0.01")) -> list[Decimal]:
        """n positive amounts summing exactly to total; all but the last are multiples of quantum."""
        w = [self.rng.uniform(*spread) for _ in range(n)]
        s = sum(w)
        parts = [((total * D(str(x / s))) / quantum).quantize(D(1)) * quantum for x in w[:-1]]
        parts = [to_money(p) for p in parts]
        last = total - sum(parts)
        assert last > 0, "split produced a non-positive remainder"
        return parts + [last]

    def masked(self) -> str:
        return f"xxx-x-x{self.rng.randint(1000, 9999)}-x"

    def add(self, t: SynthTxn) -> SynthTxn:
        self._seq += 1
        t.seq = self._seq
        self.txns.append(t)
        return t

    def transfer_in(self, acct: str, at: datetime, amount: Decimal, name: str, bank: str, cp_acct: str,
                    category: str, memo: str = "", loop_id: str | None = None) -> None:
        details = f"จาก {name} {bank} {cp_acct}" + (f" {memo}" if memo else "")
        self.add(SynthTxn(acct, at, "TR-IN", self.rng.choice(["MOBILE", "INTERNET"]), details, category,
                          credit=amount, counterparty=name, counterparty_bank=bank,
                          counterparty_account=cp_acct, loop_id=loop_id))

    def transfer_out(self, acct: str, at: datetime, amount: Decimal, name: str, bank: str, cp_acct: str,
                     category: str, memo: str = "", loop_id: str | None = None, fee: bool = False) -> None:
        details = f"ไปยัง {name} {bank} {cp_acct}" + (f" {memo}" if memo else "")
        self.add(SynthTxn(acct, at, "TR-OUT", self.rng.choice(["MOBILE", "INTERNET"]), details, category,
                          debit=amount, counterparty=name, counterparty_bank=bank,
                          counterparty_account=cp_acct, loop_id=loop_id))

    # ---------- scenario sections ----------
    def revenue(self) -> None:
        rev = self.rev = self.sc.revenue
        weights_t1 = [("BBL_CUR", 0.7), ("KBANK_SAV", 0.3)]

        def pick(weights: list[tuple[str, float]]) -> str:
            return self.rng.choices([k for k, _ in weights], [w for _, w in weights])[0]

        cust_accts = {name: self.masked() for name, _ in T1_CUSTOMERS + T2_CUSTOMERS}
        for amt in self.split_exact(rev.tiers["T1_golden"], 48, (0.3, 1.7)):
            name, bank = self.rng.choice(T1_CUSTOMERS)
            self.transfer_in(pick(weights_t1), self.rand_dt(), amt, name, bank, cust_accts[name], REVENUE_T1)
        for amt in self.split_exact(rev.tiers["T2_tax"], 64, (0.3, 1.7)):
            name, bank = self.rng.choice(T2_CUSTOMERS)
            acct = pick([("BBL_CUR", 0.4), ("KBANK_SAV", 0.4), ("SCB_SAV", 0.2)])
            self.transfer_in(acct, self.rand_dt(), amt, name, bank, cust_accts[name], REVENUE_T2)
        for amt in self.split_exact(rev.tiers["T3_operational"], 300, (0.3, 1.7)):
            payer = f"{self.rng.choice(T3_PAYER_PREFIX)} {self.rng.choice(T3_PAYER_NAMES)} {self.rng.choice('กขคงจฉชซดตทนบปผพมยรลวสหอ')}***"
            self.add(SynthTxn("SCB_SAV", self.rand_dt(hours=(9, 21)), "PP-IN", "PROMPTPAY",
                              f"รับเงินพร้อมเพย์ จาก {payer}", REVENUE_T3, credit=amt, counterparty=payer))

    def unverified(self) -> None:
        homes = ["BBL_CUR", "KBANK_SAV", "SCB_SAV"]
        for w, acct in zip(self.sc.watchlist, homes):
            at = datetime.combine(w.date, time(11, 5) if acct == "BBL_CUR" else time(10, 12))
            if w.description == "CASH DEPOSIT":
                self.add(SynthTxn(acct, at, "CD", "COUNTER", "ฝากเงินสด", UNVERIFIED, credit=w.amount,
                                  counterparty=None))
            else:
                self.transfer_in(acct, at, w.amount, w.counterparty, "SCB", self.masked(), UNVERIFIED,
                                 memo=w.description)

    def owner_money(self) -> None:
        director = next(a for a in self.sc.accounts if a.owner_type == "director")
        company_names = {a.key: a for a in self.sc.accounts if a.owner_type == "company"}
        # 700,000 from the director's own account (both legs visible: debit on director, credit on company)
        for amt, dest, day in [(D("400000.00"), "BBL_CUR", date(2026, 1, 20)), (D("300000.00"), "SCB_SAV", date(2026, 4, 9))]:
            at = datetime.combine(day, time(9, 40))
            dst = company_names[dest]
            self.transfer_out(director.key, at, amt, dst.account_name, dst.bank_code, dst.account_no_masked,
                              OWNER_INJECTION, memo="เพิ่มทุนหมุนเวียน")
            self.transfer_in(dest, at + timedelta(minutes=1), amt, director.account_name, director.bank_code,
                             director.account_no_masked, OWNER_INJECTION, memo="เพิ่มทุนหมุนเวียน")
        # 500,000 from a family member whose account is not in the file
        bank, acct = FAMILY_MEMBER_ACCT
        for day in (date(2026, 2, 3), date(2026, 5, 6)):
            self.transfer_in("BBL_CUR", datetime.combine(day, time(13, 15)), D("250000.00"), self.family_member,
                             bank, acct, OWNER_INJECTION)
        assert D("1200000.00") == self.sc.revenue.owner_family_inflow

    def loops(self) -> None:
        for loop in self.sc.loops:
            for leg in loop.legs:
                src, dst = self.accounts[leg.from_], self.accounts[leg.to]
                self.transfer_out(src.key, leg.at, leg.amount, dst.account_name, dst.bank_code,
                                  dst.account_no_masked, LOOP, loop_id=loop.id)
                self.transfer_in(dst.key, leg.at + timedelta(minutes=2), leg.amount, src.account_name,
                                 src.bank_code, src.account_no_masked, LOOP, loop_id=loop.id)

    def debt_and_household(self) -> None:
        for y, m in self.months:
            self.add(SynthTxn("BBL_CUR", datetime(y, m, 5, 7, 30), "LOAN", "AUTO",
                              "ชำระค่างวดสินเชื่อธุรกิจ (สถาบันการเงินอื่น) LN-88213", DEBT_SERVICE,
                              debit=self.sc.existing_debt_service_monthly, counterparty="สินเชื่อธุรกิจ สถาบันการเงินอื่น"))
        bank, acct = FAMILY_MEMBER_ACCT
        items: list[tuple[datetime, Decimal, str, str]] = []
        for y, m in self.months:
            items.append((datetime(y, m, 15, 8, 0), D("40000.00"), "BILL", "ค่างวดรถยนต์ส่วนบุคคล สัญญา HP-5521"))
            items.append((self.rand_dt((y, m)), D("60000.00"), "TR-OUT", f"ไปยัง {self.family_member} {bank} {acct} ค่าใช้จ่ายบ้าน"))
        items.append((datetime(2026, 1, 8, 10, 0), D("150000.00"), "BILL", "ค่าเทอม รร.นานาชาติ บุตร ภาคเรียนที่ 2"))
        items.append((datetime(2026, 5, 12, 10, 0), D("150000.00"), "BILL", "ค่าเทอม รร.นานาชาติ บุตร ภาคเรียนที่ 1"))
        for at, amt, code, details in items:
            cp = self.family_member if code == "TR-OUT" else None
            self.add(SynthTxn("BBL_CUR", at, code, "MOBILE" if code == "TR-OUT" else "AUTO", details, HOUSEHOLD,
                              debit=amt, counterparty=cp,
                              counterparty_account=acct if code == "TR-OUT" else None))
        assert sum(a for _, a, _, _ in items) == self.sc.costs.household_6m

    def business_costs(self) -> None:
        total = self.sc.costs.business_operating_6m
        fixed: list[SynthTxn] = []
        for y, m in self.months:
            last = self._days_in_month(y, m)[-1]
            fixed.append(SynthTxn("KBANK_SAV", datetime.combine(last, time(8, 0)), "PAYROLL", "AUTO",
                                  "PAYROLL เงินเดือนพนักงาน 14 ราย", BUSINESS_COST,
                                  debit=to_money(self.rng.randint(400_000, 440_000))))
            fixed.append(SynthTxn("BBL_CUR", datetime(y, m, 1, 9, 0), "TR-OUT", "INTERNET",
                                  "ไปยัง บจก. พรีเมียร์ แลนด์ KTB xxx-x-x1182-x ค่าเช่าโกดังและสำนักงาน", BUSINESS_COST,
                                  debit=D("85000.00"), counterparty="บจก. พรีเมียร์ แลนด์"))
            fixed.append(SynthTxn("BBL_CUR", datetime(y, m, 20, 6, 0), "BILL", "AUTO", "ค่าไฟฟ้า การไฟฟ้า CA-0205518",
                                  BUSINESS_COST, debit=to_money(round(self.rng.uniform(15000, 28000), 2)),
                                  counterparty="การไฟฟ้า"))
            fixed.append(SynthTxn("BBL_CUR", datetime(y, m, 22, 6, 0), "BILL", "AUTO", "ค่าน้ำประปา CA-7741029",
                                  BUSINESS_COST, debit=to_money(round(self.rng.uniform(2000, 4000), 2)),
                                  counterparty="การประปา"))
        # Mon/Thu cash withdrawals for site labour and materials bought on site
        for _ in range(52):
            acct = self.rng.choice(["SCB_SAV", "BBL_CUR"])
            fixed.append(SynthTxn(acct, self.rand_dt(weekdays={0, 3}, hours=(7, 10)), "CW",
                                  self.rng.choice(["ATM", "COUNTER"]), "ถอนเงินสด", BUSINESS_COST,
                                  debit=to_money(self.rng.randint(30, 90) * 1000)))
        # Supplier payments, each with an inter-bank transfer fee
        n_sup = 320
        fees = [to_money(self.rng.choice([10, 15, 20, 25])) for _ in range(n_sup)]
        supplier_total = total - sum(t.debit for t in fixed) - sum(fees)
        sup_accts = {name: self.masked() for name, _ in SUPPLIERS}
        for amt, fee in zip(self.split_exact(supplier_total, n_sup, (0.2, 1.8)), fees):
            name, bank = self.rng.choice(SUPPLIERS)
            acct = self.rng.choices(["BBL_CUR", "KBANK_SAV"], [0.7, 0.3])[0]
            at = self.rand_dt()
            self.transfer_out(acct, at, amt, name, bank, sup_accts[name], BUSINESS_COST,
                              memo=f"PO-{self.rng.randint(1000, 9999)}")
            self.add(SynthTxn(acct, at + timedelta(minutes=1), "FEE", "AUTO", "ค่าธรรมเนียมโอนต่างธนาคาร",
                              BUSINESS_COST, debit=fee))
        for t in fixed:
            self.add(t)

    def director_personal(self) -> None:
        director = next(a for a in self.sc.accounts if a.owner_type == "director")
        for _ in range(28):
            self.add(SynthTxn(director.key, self.rand_dt(hours=(8, 22)), "BILL", "MOBILE",
                              self.rng.choice(["ชำระบัตรเครดิต", "ค่าอาหาร", "ค่าโทรศัพท์", "ค่าน้ำมัน", "ช้อปปิ้งออนไลน์"]),
                              DIRECTOR_PERSONAL, debit=to_money(self.rng.randint(2, 40) * 500)))

    # ---------- balances ----------
    def finalize(self) -> dict[str, GeneratedAccount]:
        out = {}
        for key, spec in self.accounts.items():
            rows = sorted((t for t in self.txns if t.account == key), key=lambda t: (t.at, t.seq))
            running, low = ZERO, ZERO
            for t in rows:
                running += t.credit - t.debit
                low = min(low, running)
            # Opening balance: enough that the account never goes negative, rounded up to 10,000.
            base = D("500000.00") if spec.owner_type == "company" else D("2500000.00")
            need = -low + D("150000")
            opening = max(base, ((need / 10000).to_integral_value(rounding="ROUND_CEILING")) * 10000)
            opening = to_money(opening)
            bal = opening
            for t in rows:
                bal += t.credit - t.debit
                t.balance = bal
            out[key] = GeneratedAccount(spec, opening, rows)
        return out


def generate(sc: Scenario, seed: int = 42) -> GeneratedCase:
    g = _Gen(sc, seed)
    g.revenue()
    g.unverified()
    g.owner_money()
    g.loops()
    g.debt_and_household()
    g.business_costs()
    g.director_personal()
    return GeneratedCase(sc, g.finalize(), seed)
