"""Deterministic financial engine for LedgerLens AI.

All money arithmetic lives here, uses ``decimal.Decimal`` and is covered by tests.
The AI model never calculates figures; it only explains what this module produces.

CONVENTIONS (read these first)
------------------------------
* ``transactions``  = completed HISTORICAL cash movements. They are the only thing
  that changes current cash:  cash = opening_balance + income - expenses
  (completed transactions dated on or before today).
* ``obligations``   = bills we still OWE. An unpaid obligation is NOT in the
  transaction list, so it is counted exactly once, as a future outflow.
* ``receivables``   = customer money we EXPECT. Pending receivables are NOT cash and
  are NOT in the transaction list; they are counted only as expected inflows.
* Paying an obligation / receiving a receivable marks it Paid / Received AND
  creates the matching transaction (see ``mark_obligation_paid``), so nothing is
  ever counted twice. Paid/Received items are excluded from projections.
* Overdue unpaid obligations are assumed to be paid today (worst case for cash).
  Overdue receivables are NOT assumed to arrive (conservative) unless requested.
* Future-dated transactions are rejected when adding records; the projection only
  looks forward using obligations, receivables and the hypothetical purchase.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

ZERO = Decimal("0")
CENT = Decimal("0.01")
DATA_DIR = Path(__file__).parent  
DUE_SOON_DAYS = 7
# Opening balance of the fictional business before the first sample transaction.
DEFAULT_OPENING_BALANCE = Decimal("124300")

TX_COLS = ["id", "date", "description", "category", "type", "amount", "status", "counterparty", "notes"]
OBL_COLS = ["id", "description", "category", "amount", "due_date", "payment_status", "counterparty"]
REC_COLS = ["id", "description", "counterparty", "amount", "expected_date", "payment_status"]


# --------------------------------------------------------------------------- #
# Basic helpers
# --------------------------------------------------------------------------- #
def to_money(value) -> Decimal:
    """Convert to a 2-decimal Decimal. Raises ValueError for junk input."""
    if isinstance(value, Decimal):
        d = value
    else:
        try:
            d = Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, ValueError):
            raise ValueError(f"Invalid amount: {value!r}")
    if not d.is_finite():
        raise ValueError(f"Invalid amount: {value!r}")
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def format_pkr(value) -> str:
    d = to_money(value)
    sign = "-" if d < 0 else ""
    d = abs(d)
    if d == d.to_integral_value():
        return f"{sign}PKR {d:,.0f}"
    return f"{sign}PKR {d:,.2f}"


def to_date(value) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"Invalid date: {value!r}")


def fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def sum_money(values: Iterable) -> Decimal:
    return sum((Decimal(v) for v in values), ZERO)


def _filter(df: pd.DataFrame, pred: Callable[[dict], bool]) -> pd.DataFrame:
    """Row filter that is safe for empty frames."""
    return df.loc[[bool(pred(r)) for r in df.to_dict("records")]]


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class DemoData:
    transactions: pd.DataFrame
    obligations: pd.DataFrame
    receivables: pd.DataFrame
    opening_balance: Decimal = ZERO


def _prepare(rows, cols, text_cols, money_col, date_cols) -> pd.DataFrame:
    df = pd.DataFrame(list(rows)).reindex(columns=cols)
    for c in text_cols:
        df[c] = df[c].fillna("").astype(str).str.strip()
    df[money_col] = [to_money(v) for v in df[money_col]]
    for c in date_cols:
        df[c] = [to_date(v) for v in df[c]]
    return df.reset_index(drop=True)


def normalize_transactions(rows) -> pd.DataFrame:
    df = _prepare(rows, TX_COLS, ["id", "description", "category", "type", "status", "counterparty", "notes"],
                  "amount", ["date"])
    df["type"] = df["type"].str.lower()
    df["status"] = [s or "Completed" for s in df["status"]]
    if not df["type"].isin(["income", "expense"]).all():
        raise ValueError("Transaction type must be 'income' or 'expense'.")
    return df


def normalize_obligations(rows) -> pd.DataFrame:
    df = _prepare(rows, OBL_COLS, ["id", "description", "category", "payment_status", "counterparty"],
                  "amount", ["due_date"])
    df["payment_status"] = [s or "Unpaid" for s in df["payment_status"]]
    return df


def normalize_receivables(rows) -> pd.DataFrame:
    df = _prepare(rows, REC_COLS, ["id", "description", "counterparty", "payment_status"],
                  "amount", ["expected_date"])
    df["payment_status"] = [s or "Pending" for s in df["payment_status"]]
    return df


def build_data(transactions=(), obligations=(), receivables=(), opening_balance=ZERO) -> DemoData:
    return DemoData(normalize_transactions(transactions), normalize_obligations(obligations),
                    normalize_receivables(receivables), to_money(opening_balance))


def load_sample_data(today: Optional[date] = None) -> DemoData:
    """Load fictional CSV data. ``day_offset`` is relative to today so the demo never goes stale."""
    today = today or date.today()

    def read(name: str, date_col: str):
        df = pd.read_csv(DATA_DIR / name, dtype=str, keep_default_na=False)
        df[date_col] = [today + timedelta(days=int(o)) for o in df.pop("day_offset")]
        return df.to_dict("records")

    return build_data(read("sample_transactions.csv", "date"),
                      read("sample_obligations.csv", "due_date"),
                      read("sample_receivables.csv", "expected_date"),
                      DEFAULT_OPENING_BALANCE)


# --------------------------------------------------------------------------- #
# Statuses
# --------------------------------------------------------------------------- #
def obligation_status(payment_status: str, due: date, today: date) -> str:
    if str(payment_status).lower() == "paid":
        return "Paid"
    if due < today:
        return "Overdue"
    if (due - today).days <= DUE_SOON_DAYS:
        return "Due soon"
    return "Upcoming"


def receivable_status(payment_status: str, expected: date, today: date) -> str:
    if str(payment_status).lower() == "received":
        return "Received"
    return "Overdue" if expected < today else "Pending"


def obligations_with_status(obl: pd.DataFrame, today: date) -> pd.DataFrame:
    df = obl.copy()
    df["status"] = [obligation_status(p, d, today) for p, d in zip(df["payment_status"], df["due_date"])]
    df["days_until_due"] = [None if s == "Paid" else (d - today).days for s, d in zip(df["status"], df["due_date"])]
    return df


def receivables_with_status(rec: pd.DataFrame, today: date) -> pd.DataFrame:
    df = rec.copy()
    df["status"] = [receivable_status(p, d, today) for p, d in zip(df["payment_status"], df["expected_date"])]
    df["days_until_expected"] = [None if s == "Received" else (d - today).days
                                 for s, d in zip(df["status"], df["expected_date"])]
    return df


# --------------------------------------------------------------------------- #
# Cash, totals, outstanding items
# --------------------------------------------------------------------------- #
def _completed(tx: pd.DataFrame, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
    return _filter(tx, lambda r: r["status"].lower() == "completed"
                   and (start is None or r["date"] >= start) and (end is None or r["date"] <= end))


def current_cash(tx: pd.DataFrame, opening_balance: Decimal, as_of: date) -> Decimal:
    """Confirmed cash = opening balance + completed income - completed expenses up to ``as_of``."""
    done = _completed(tx, end=as_of)
    signed = [r["amount"] if r["type"] == "income" else -r["amount"] for r in done.to_dict("records")]
    return to_money(opening_balance) + sum_money(signed)


def period_totals(tx: pd.DataFrame, start: date, end: date) -> dict:
    done = _completed(tx, start, end)
    income = sum_money(done.loc[done["type"] == "income", "amount"]) if not done.empty else ZERO
    expenses = sum_money(done.loc[done["type"] == "expense", "amount"]) if not done.empty else ZERO
    return {"income": income, "expenses": expenses, "net": income - expenses}


def outstanding_obligations(obl: pd.DataFrame, today: date, upto: Optional[date] = None) -> pd.DataFrame:
    """Unpaid obligations (overdue ones included) due on or before ``upto``."""
    return _filter(obl, lambda r: r["payment_status"].lower() != "paid" and (upto is None or r["due_date"] <= upto))


def expected_receivables(rec: pd.DataFrame, today: date, upto: Optional[date] = None,
                         include_overdue: bool = False) -> pd.DataFrame:
    """Pending customer payments. Overdue ones are excluded unless ``include_overdue``."""
    def keep(r):
        if r["payment_status"].lower() == "received":
            return False
        if r["expected_date"] < today and not include_overdue:
            return False
        return upto is None or r["expected_date"] <= upto
    return _filter(rec, keep)


def total(df: pd.DataFrame) -> Decimal:
    return sum_money(df["amount"]) if not df.empty else ZERO


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Event:
    date: date
    amount: Decimal  # signed: negative = cash out, positive = cash in
    label: str
    kind: str        # obligation | receivable | purchase


def build_events(data: DemoData, today: date, horizon_end: date, include_receivables: bool = True,
                 include_overdue_receivables: bool = False) -> list[Event]:
    events = [Event(max(r["due_date"], today), -r["amount"], r["description"], "obligation")
              for r in outstanding_obligations(data.obligations, today, horizon_end).to_dict("records")]
    if include_receivables:
        rec = expected_receivables(data.receivables, today, horizon_end, include_overdue_receivables)
        events += [Event(max(r["expected_date"], today), r["amount"], r["description"], "receivable")
                   for r in rec.to_dict("records")]
    return events


def project_cash(cash: Decimal, events: list[Event], start: date, end: date) -> pd.DataFrame:
    """Daily projection. ``balance`` is the end-of-day balance."""
    inflow: dict[date, Decimal] = {}
    outflow: dict[date, Decimal] = {}
    for e in events:
        d = max(e.date, start)
        if d > end:
            continue
        if e.amount >= 0:
            inflow[d] = inflow.get(d, ZERO) + e.amount
        else:
            outflow[d] = outflow.get(d, ZERO) - e.amount
    rows, bal = [], to_money(cash)
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        inn, out = inflow.get(d, ZERO), outflow.get(d, ZERO)
        bal = bal + inn - out
        rows.append({"date": d, "inflow": inn, "outflow": out, "balance": bal})
    return pd.DataFrame(rows, columns=["date", "inflow", "outflow", "balance"])


def lowest_point(proj: pd.DataFrame) -> tuple[Optional[Decimal], Optional[date]]:
    best = None
    for r in proj.to_dict("records"):
        if best is None or r["balance"] < best["balance"]:
            best = r
    return (best["balance"], best["date"]) if best else (None, None)


def first_date_below(proj: pd.DataFrame, threshold: Decimal) -> Optional[date]:
    for r in proj.to_dict("records"):
        if r["balance"] < threshold:
            return r["date"]
    return None


def balance_on(proj: pd.DataFrame, d: date) -> Optional[Decimal]:
    for r in proj.to_dict("records"):
        if r["date"] == d:
            return r["balance"]
    return None


# --------------------------------------------------------------------------- #
# What-if simulator
# --------------------------------------------------------------------------- #
@dataclass
class Scenario:
    description: str
    amount: Decimal
    purchase_date: date
    reserve: Decimal = ZERO


def validate_scenario(s: Scenario, today: date) -> Scenario:
    if not s.description.strip():
        raise ValueError("Please describe the purchase.")
    amount, reserve = to_money(s.amount), to_money(s.reserve)
    if amount <= 0:
        raise ValueError("Purchase amount must be greater than zero.")
    if reserve < 0:
        raise ValueError("Minimum cash reserve cannot be negative.")
    pdate = to_date(s.purchase_date)
    if pdate < today:
        raise ValueError("Purchase date cannot be in the past.")
    return Scenario(s.description.strip(), amount, pdate, reserve)


@dataclass
class SimulationResult:
    scenario: Scenario
    today: date
    horizon_end: date
    include_receivables: bool
    current_cash: Decimal
    baseline: pd.DataFrame
    with_purchase: pd.DataFrame
    baseline_min: Decimal
    baseline_min_date: date
    scenario_min: Decimal
    scenario_min_date: date
    baseline_end: Decimal
    scenario_end: Decimal
    baseline_on_purchase_date: Decimal
    scenario_on_purchase_date: Decimal
    difference: Decimal
    obligations_due_by_purchase: Decimal
    receivables_by_purchase: Decimal
    baseline_below_zero: bool
    scenario_below_zero: bool
    baseline_below_reserve: bool
    scenario_below_reserve: bool
    first_shortfall_date: Optional[date]
    first_reserve_breach_date: Optional[date]


def simulate(data: DemoData, scenario: Scenario, today: date, horizon_days: int = 30,
             include_receivables: bool = True) -> SimulationResult:
    """Baseline vs. scenario. Both use identical events; the scenario only adds the purchase."""
    s = validate_scenario(scenario, today)
    horizon_end = max(today + timedelta(days=horizon_days), s.purchase_date)
    cash = current_cash(data.transactions, data.opening_balance, today)
    events = build_events(data, today, horizon_end, include_receivables)
    base = project_cash(cash, events, today, horizon_end)
    scen = project_cash(cash, events + [Event(s.purchase_date, -s.amount, s.description, "purchase")],
                        today, horizon_end)
    b_min, b_min_d = lowest_point(base)
    s_min, s_min_d = lowest_point(scen)
    b_on, s_on = balance_on(base, s.purchase_date), balance_on(scen, s.purchase_date)
    obl_due = total(outstanding_obligations(data.obligations, today, s.purchase_date))
    rec_due = total(expected_receivables(data.receivables, today, s.purchase_date)) if include_receivables else ZERO
    return SimulationResult(
        scenario=s, today=today, horizon_end=horizon_end, include_receivables=include_receivables,
        current_cash=cash, baseline=base, with_purchase=scen,
        baseline_min=b_min, baseline_min_date=b_min_d, scenario_min=s_min, scenario_min_date=s_min_d,
        baseline_end=base.iloc[-1]["balance"], scenario_end=scen.iloc[-1]["balance"],
        baseline_on_purchase_date=b_on, scenario_on_purchase_date=s_on,
        difference=s.amount, obligations_due_by_purchase=obl_due, receivables_by_purchase=rec_due,
        baseline_below_zero=b_min < 0, scenario_below_zero=s_min < 0,
        baseline_below_reserve=b_min < s.reserve, scenario_below_reserve=s_min < s.reserve,
        first_shortfall_date=first_date_below(scen, ZERO),
        first_reserve_breach_date=first_date_below(scen, s.reserve),
    )


def scenario_messages(r: SimulationResult) -> list[tuple[str, str]]:
    """Cautious, plain-language verdicts as (level, text); level is error/warning/success/info."""
    s, out = r.scenario, []
    if r.scenario_below_zero:
        out.append(("error", f"This scenario creates a projected cash shortfall on {fmt_date(r.first_shortfall_date)}. "
                             f"The lowest projected balance is {format_pkr(r.scenario_min)} on {fmt_date(r.scenario_min_date)}."))
    elif r.scenario_below_reserve:
        out.append(("warning", f"The projected balance falls below your selected cash reserve of {format_pkr(s.reserve)} "
                               f"on {fmt_date(r.first_reserve_breach_date)}. Lowest projected balance: "
                               f"{format_pkr(r.scenario_min)} on {fmt_date(r.scenario_min_date)}."))
    else:
        out.append(("success", f"This scenario is projected to leave at least {format_pkr(r.scenario_min)} available "
                               f"through {fmt_date(r.horizon_end)} (lowest on {fmt_date(r.scenario_min_date)}), "
                               f"which stays above your reserve of {format_pkr(s.reserve)}."))
    if r.baseline_below_zero:
        out.append(("warning", "Even without the purchase, the baseline projection already falls below zero."))
    elif r.baseline_below_reserve and r.scenario_below_reserve:
        out.append(("info", "The baseline (without the purchase) is already below your reserve at its lowest point."))
    if r.include_receivables:
        out.append(("info", "The result depends on the timing of expected receivables, which are not guaranteed cash."))
    else:
        out.append(("info", "Conservative view: expected customer receivables are excluded from this projection."))
    return out


# --------------------------------------------------------------------------- #
# Insights and alerts (rule-based, no AI)
# --------------------------------------------------------------------------- #
@dataclass
class Insight:
    level: str   # error | warning | info
    message: str


_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}


def generate_insights(data: DemoData, today: date, reserve: Decimal = ZERO, horizon_days: int = 30,
                      sim: Optional[SimulationResult] = None, limit: int = 8) -> list[Insight]:
    out: list[Insight] = []
    horizon_end = today + timedelta(days=horizon_days)
    obl = obligations_with_status(outstanding_obligations(data.obligations, today), today)

    overdue = obl[obl["status"] == "Overdue"] if not obl.empty else obl
    if not overdue.empty:
        out.append(Insight("error", f"{len(overdue)} overdue obligation(s) totalling {format_pkr(total(overdue))} "
                                    f"(largest: {overdue.sort_values('amount').iloc[-1]['description']})."))
    soon = obl[obl["status"] == "Due soon"] if not obl.empty else obl
    if not soon.empty:
        out.append(Insight("warning", f"You have {format_pkr(total(soon))} in obligations due within the next "
                                      f"{DUE_SOON_DAYS} days ({len(soon)} item(s))."))
    upcoming = _filter(obl, lambda r: r["due_date"] >= today and r["due_date"] <= horizon_end)
    if not upcoming.empty:
        big = upcoming.sort_values("amount").iloc[-1]
        out.append(Insight("info", f"Your largest upcoming obligation is {big['description']} "
                                   f"({format_pkr(big['amount'])}), due on {fmt_date(big['due_date'])}."))

    cash = current_cash(data.transactions, data.opening_balance, today)
    base = project_cash(cash, build_events(data, today, horizon_end), today, horizon_end)
    b_min, b_min_d = lowest_point(base)
    if b_min is not None and b_min < 0:
        out.append(Insight("error", f"The projected balance falls below zero on {fmt_date(first_date_below(base, ZERO))} "
                                    f"(lowest {format_pkr(b_min)})."))
    elif b_min is not None and reserve > 0 and b_min < reserve:
        out.append(Insight("warning", f"Your projected balance falls below your minimum cash reserve of "
                                      f"{format_pkr(reserve)} on {fmt_date(first_date_below(base, reserve))}."))

    rec = expected_receivables(data.receivables, today, horizon_end)
    if not rec.empty:
        out.append(Insight("info", f"Your expected receivables are {format_pkr(total(rec))} over the next "
                                   f"{horizon_days} days (expected, not yet received)."))
        if len(rec) >= 2:
            by_day = rec.groupby("expected_date")["amount"].apply(sum_money)
            top_day, top_amt = by_day.idxmax(), by_day.max()
            if top_amt > total(rec) / 2:
                out.append(Insight("info", f"Expected receivables are concentrated on {fmt_date(top_day)} "
                                           f"({format_pkr(top_amt)}); a late payment would matter."))
    late = _filter(data.receivables, lambda r: r["payment_status"].lower() != "received" and r["expected_date"] < today)
    if not late.empty:
        out.append(Insight("warning", f"{len(late)} expected receivable(s) totalling {format_pkr(total(late))} "
                                      f"have not yet been received. They are excluded from projections."))
    if sim is not None:
        out.append(Insight("info", f"Your scenario '{sim.scenario.description}' reduces the projected balance by "
                                   f"{format_pkr(sim.difference)}."))
        for level, msg in scenario_messages(sim)[:1]:
            if level in ("error", "warning"):
                out.append(Insight(level, msg))
    out.sort(key=lambda i: _LEVEL_ORDER[i.level])
    return out[:limit]


# --------------------------------------------------------------------------- #
# Snapshot for the AI (JSON-serialisable, produced from the functions above)
# --------------------------------------------------------------------------- #
def _m(v) -> str:
    return str(to_money(v))


def _sim_block(r: SimulationResult) -> dict:
    return {
        "purchase_description": r.scenario.description[:120],
        "purchase_amount": _m(r.scenario.amount),
        "purchase_date": r.scenario.purchase_date.isoformat(),
        "minimum_cash_reserve": _m(r.scenario.reserve),
        "includes_expected_receivables": r.include_receivables,
        "baseline_balance_on_purchase_date": _m(r.baseline_on_purchase_date),
        "scenario_balance_on_purchase_date": _m(r.scenario_on_purchase_date),
        "baseline_lowest_balance": {"amount": _m(r.baseline_min), "date": r.baseline_min_date.isoformat()},
        "scenario_lowest_balance": {"amount": _m(r.scenario_min), "date": r.scenario_min_date.isoformat()},
        "baseline_balance_at_horizon_end": _m(r.baseline_end),
        "scenario_balance_at_horizon_end": _m(r.scenario_end),
        "difference_caused_by_purchase": _m(r.difference),
        "obligations_due_by_purchase_date": _m(r.obligations_due_by_purchase),
        "expected_receivables_by_purchase_date": _m(r.receivables_by_purchase),
        "creates_projected_shortfall": r.scenario_below_zero,
        "first_shortfall_date": r.first_shortfall_date.isoformat() if r.first_shortfall_date else None,
        "breaches_minimum_reserve": r.scenario_below_reserve,
        "first_reserve_breach_date": r.first_reserve_breach_date.isoformat() if r.first_reserve_breach_date else None,
        "baseline_already_below_reserve": r.baseline_below_reserve,
        "baseline_already_below_zero": r.baseline_below_zero,
    }


def build_snapshot(data: DemoData, today: date, period_start: date, period_end: date,
                   scenario: Optional[Scenario] = None, horizon_days: int = 30,
                   reserve: Decimal = ZERO) -> dict:
    """Everything the AI is allowed to know, with every amount labelled by what it represents."""
    horizon_end = today + timedelta(days=horizon_days)
    cash = current_cash(data.transactions, data.opening_balance, today)
    totals = period_totals(data.transactions, period_start, period_end)

    obl = obligations_with_status(outstanding_obligations(data.obligations, today), today)
    obl = obl.sort_values("due_date") if not obl.empty else obl
    rec = receivables_with_status(
        _filter(data.receivables, lambda r: r["payment_status"].lower() != "received"), today)
    rec = rec.sort_values("expected_date") if not rec.empty else rec

    base = project_cash(cash, build_events(data, today, horizon_end), today, horizon_end)
    b_min, b_min_d = lowest_point(base)
    events_only = [r for r in base.to_dict("records") if r["inflow"] or r["outflow"]][:25]

    recent = data.transactions.sort_values("date", ascending=False).head(8) if not data.transactions.empty else data.transactions
    sim, sim_conservative, note = None, None, None
    if scenario is not None:
        try:
            sim = simulate(data, scenario, today, horizon_days, True)
            sim_conservative = simulate(data, scenario, today, horizon_days, False)
        except ValueError as exc:
            note = f"Scenario could not be calculated: {exc}"

    return {
        "notice": "SIMULATED DEMO DATA. No real bank account is connected.",
        "currency": "PKR",
        "as_of_date": today.isoformat(),
        "current_available_cash": {"amount": _m(cash),
                                   "meaning": "Confirmed cash today (opening balance + completed transactions)."},
        "reporting_period": {"start": period_start.isoformat(), "end": period_end.isoformat(),
                             "income": _m(totals["income"]), "expenses": _m(totals["expenses"]),
                             "net_cash_flow": _m(totals["net"]),
                             "meaning": "Completed historical transactions only."},
        "outstanding_obligations": [
            {"id": r["id"], "description": r["description"][:80], "category": r["category"],
             "amount": _m(r["amount"]), "due_date": r["due_date"].isoformat(), "status": r["status"],
             "days_until_due": r["days_until_due"]} for r in obl.head(15).to_dict("records")],
        "expected_receivables": [
            {"id": r["id"], "description": r["description"][:80], "customer": r["counterparty"][:60],
             "amount": _m(r["amount"]), "expected_date": r["expected_date"].isoformat(), "status": r["status"],
             "days_until_expected": r["days_until_expected"]} for r in rec.head(15).to_dict("records")],
        "receivables_note": "Expected receivables are NOT cash and are not guaranteed. Overdue ones are "
                            "excluded from projections.",
        "baseline_projection": {
            "horizon_end": horizon_end.isoformat(),
            "lowest_balance": _m(b_min), "lowest_balance_date": b_min_d.isoformat(),
            "balance_at_horizon_end": _m(base.iloc[-1]["balance"]),
            "cash_movement_days": [{"date": r["date"].isoformat(), "inflow": _m(r["inflow"]),
                                    "outflow": _m(r["outflow"]), "end_of_day_balance": _m(r["balance"])}
                                   for r in events_only],
        },
        "active_scenario": _sim_block(sim) if sim else None,
        "active_scenario_if_expected_receivables_never_arrive": _sim_block(sim_conservative) if sim_conservative else None,
        "scenario_note": note or (None if scenario else "No what-if scenario has been run in the simulator yet."),
        "rule_based_insights": [i.message for i in generate_insights(data, today, reserve, horizon_days, sim, 6)],
        "recent_transactions": [
            {"date": r["date"].isoformat(), "description": r["description"][:80], "category": r["category"],
             "type": r["type"], "amount": _m(r["amount"])} for r in recent.to_dict("records")],
        "assumptions": [
            "Unpaid obligations are paid on their due date; overdue ones are assumed paid today.",
            "Pending receivables arrive on their expected date; overdue receivables are excluded.",
            "Paid obligations and received receivables are already reflected in current cash.",
            "Projections are forecasts from recorded data, not guarantees.",
        ],
    }


# --------------------------------------------------------------------------- #
# Record changes (return NEW DemoData, never mutate)
# --------------------------------------------------------------------------- #
def _next_id(df: pd.DataFrame, prefix: str) -> str:
    nums = [int(re.sub(r"\D", "", i) or 0) for i in df["id"]] if not df.empty else []
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


def _append(df: pd.DataFrame, row: dict, cols: list[str]) -> pd.DataFrame:
    new = pd.DataFrame([row], columns=cols)
    return new if df.empty else pd.concat([df, new], ignore_index=True)


def add_transaction(data: DemoData, *, txn_date, description: str, category: str, txn_type: str, amount,
                    counterparty: str = "", notes: str = "", today: Optional[date] = None) -> DemoData:
    """Validate and add a completed transaction. Raises ValueError on bad input or duplicates."""
    today = today or date.today()
    desc = (description or "").strip()
    if not desc:
        raise ValueError("Description is required.")
    ttype = (txn_type or "").strip().lower()
    if ttype not in ("income", "expense"):
        raise ValueError("Type must be income or expense.")
    amt = to_money(amount)
    if amt <= 0:
        raise ValueError("Amount must be greater than zero.")
    d = to_date(txn_date)
    if d > today:
        raise ValueError("Transactions cannot be dated in the future. Use Bills & Receivables for future items.")
    cat = (category or "").strip() or "Other"
    dup = _filter(data.transactions, lambda r: r["date"] == d and r["amount"] == amt and r["type"] == ttype
                  and r["description"].lower() == desc.lower())
    if not dup.empty:
        raise ValueError("A matching transaction already exists (duplicate submission ignored).")
    row = {"id": _next_id(data.transactions, "T"), "date": d, "description": desc, "category": cat, "type": ttype,
           "amount": amt, "status": "Completed", "counterparty": (counterparty or "").strip(),
           "notes": (notes or "").strip()}
    return replace(data, transactions=_append(data.transactions, row, TX_COLS))


def _settle(data: DemoData, table: str, item_id: str, paid_date, today: date) -> DemoData:
    d = to_date(paid_date)
    if d > today:
        raise ValueError("Settlement date cannot be in the future.")
    is_obl = table == "obligations"
    df = data.obligations if is_obl else data.receivables
    idx = df.index[df["id"] == item_id]
    if len(idx) == 0:
        raise ValueError(f"Unknown item: {item_id}")
    item = df.loc[idx[0]]
    if str(item["payment_status"]).lower() in ("paid", "received"):
        raise ValueError("This item is already settled.")
    df = df.copy()
    df.loc[idx[0], "payment_status"] = "Paid" if is_obl else "Received"
    row = {"id": _next_id(data.transactions, "T"), "date": d, "status": "Completed", "amount": item["amount"],
           "description": f"{'Payment' if is_obl else 'Receipt'}: {item['description']}",
           "category": item["category"] if is_obl else "Sales",
           "type": "expense" if is_obl else "income", "counterparty": item["counterparty"],
           "notes": f"Settles {item_id}"}
    txs = _append(data.transactions, row, TX_COLS)
    return replace(data, transactions=txs, **({"obligations": df} if is_obl else {"receivables": df}))


def mark_obligation_paid(data: DemoData, obligation_id: str, paid_date, today: Optional[date] = None) -> DemoData:
    """Mark paid AND record the expense, so the bill leaves 'outstanding' and cash drops exactly once."""
    return _settle(data, "obligations", obligation_id, paid_date, today or date.today())


def mark_receivable_received(data: DemoData, receivable_id: str, received_date, today: Optional[date] = None) -> DemoData:
    """Mark received AND record the income, so it leaves 'expected' and cash rises exactly once."""
    return _settle(data, "receivables", receivable_id, received_date, today or date.today())
