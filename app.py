"""LedgerLens AI - Streamlit UI. Run with:  streamlit run app.py"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ai_assistant as ai
import finance as fin

st.set_page_config(page_title="LedgerLens AI", page_icon="📊", layout="wide")

NAVY, BLUE, TEAL, RED, AMBER, GREY = "#0b1f3a", "#2563eb", "#0f9d8a", "#dc2626", "#d97706", "#64748b"
TODAY = date.today()

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1250px;}
h1, h2, h3 {color: #0b1f3a; letter-spacing: -0.01em;}
[data-testid="stMetric"] {background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px 16px;}
[data-testid="stMetricLabel"] {color: #64748b;}
.demo-banner {background: #eff6ff; border: 1px solid #bfdbfe; color: #1e3a8a; padding: 8px 14px;
              border-radius: 10px; font-size: 0.85rem; margin-bottom: 0.8rem;}
.tagline {color: #64748b; margin-top: -0.6rem; margin-bottom: 0.6rem;}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ state
def init_state() -> None:
    if "data" not in st.session_state:
        st.session_state.data = fin.load_sample_data(TODAY)
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("awaiting", False)
    st.session_state.setdefault("scenario", None)   # last valid simulator inputs (shared with the copilot)


def reset_demo() -> None:
    for key in ("data", "chat", "awaiting", "scenario"):
        st.session_state.pop(key, None)


def money(v) -> str:
    return fin.format_pkr(v)


def to_float(series) -> list[float]:
    return [float(v) for v in series]


def style_df(df: pd.DataFrame, colour_col: str | None = None, colours: dict | None = None):
    if colour_col and colour_col in df.columns and colours:
        return df.style.map(lambda v: f"color: {colours.get(v, 'inherit')}; font-weight: 600", subset=[colour_col])
    return df


def banner() -> None:
    st.markdown('<div class="demo-banner"><b>DEMO MODE</b> — All financial information is simulated. '
                'No real bank account is connected.</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ sidebar
def sidebar() -> tuple[str, date, date, int, str]:
    with st.sidebar:
        st.markdown("## LedgerLens AI")
        st.caption("See your cash flow. Test your decisions. Plan with confidence.")
        page = st.radio("Navigate", ["Overview", "Transactions", "Bills & Receivables", "What-If Simulator",
                                     "AI Financial Copilot"], label_visibility="collapsed")
        st.divider()
        choice = st.selectbox("Reporting period", ["Last 30 days", "Last 7 days", "Current month", "Custom range"])
        if choice == "Last 30 days":
            start, end = TODAY - timedelta(days=30), TODAY
        elif choice == "Last 7 days":
            start, end = TODAY - timedelta(days=7), TODAY
        elif choice == "Current month":
            start, end = TODAY.replace(day=1), TODAY
        else:
            rng = st.date_input("Date range", (TODAY - timedelta(days=30), TODAY))
            start, end = (rng[0], rng[1]) if isinstance(rng, (tuple, list)) and len(rng) == 2 else (TODAY - timedelta(days=30), TODAY)
        horizon = st.slider("Upcoming window (days)", 7, 60, 30,
                            help="Used for upcoming obligations, expected receivables and the forecast.")
        st.divider()
        st.caption(f"Business: **Northstar Office Supplies** (fictional)  \nToday: {fin.fmt_date(TODAY)}")
        if st.button("Reset demo data", width="stretch"):
            reset_demo()
            st.rerun()
    return page, start, end, horizon, choice


# ------------------------------------------------------------------ pages
def page_overview(d: fin.DemoData, start: date, end: date, horizon: int) -> None:
    st.title("Overview")
    banner()
    cash = fin.current_cash(d.transactions, d.opening_balance, TODAY)
    tot = fin.period_totals(d.transactions, start, end)
    h_end = TODAY + timedelta(days=horizon)
    obl = fin.total(fin.outstanding_obligations(d.obligations, TODAY, h_end))
    rec = fin.total(fin.expected_receivables(d.receivables, TODAY, h_end))
    reserve = Decimal(st.session_state.scenario["reserve"]) if st.session_state.scenario else fin.ZERO

    c = st.columns(3)
    c[0].metric("Available cash", money(cash), help="Confirmed cash today: opening balance + completed transactions.")
    c[1].metric("Income (period)", money(tot["income"]), help=f"{fin.fmt_date(start)} – {fin.fmt_date(end)}")
    c[2].metric("Expenses (period)", money(tot["expenses"]))
    c = st.columns(3)
    c[0].metric("Net cash flow (period)", money(tot["net"]))
    c[1].metric(f"Upcoming obligations ({horizon}d)", money(obl), help="Unpaid bills due in the window, overdue included.")
    c[2].metric(f"Expected receivables ({horizon}d)", money(rec),
                help="Customer payments EXPECTED, not yet received. Not part of available cash.")

    st.subheader("Alerts and insights")
    insights = fin.generate_insights(d, TODAY, reserve, horizon)
    if not insights:
        st.success("No alerts: nothing urgent in the recorded data.")
    for i in insights:
        {"error": st.error, "warning": st.warning, "info": st.info}[i.level](i.message)

    t1, t2 = st.tabs(["Historical cash flow", "Projected balance (forecast)"])
    with t1:
        done = d.transactions[[s.lower() == "completed" and start <= dt <= end
                               for s, dt in zip(d.transactions["status"], d.transactions["date"])]] if not d.transactions.empty else d.transactions
        if done.empty:
            st.info("No completed transactions in this period.")
        else:
            freq = "W" if (end - start).days > 45 else "D"
            df = pd.DataFrame({"date": pd.to_datetime(done["date"]), "amount": to_float(done["amount"]), "type": done["type"]})
            piv = df.pivot_table(index=pd.Grouper(key="date", freq=freq), columns="type", values="amount", aggfunc="sum").fillna(0)
            for col in ("income", "expense"):
                if col not in piv:
                    piv[col] = 0.0
            fig = go.Figure()
            fig.add_bar(x=piv.index, y=piv["income"], name="Inflows", marker_color=TEAL)
            fig.add_bar(x=piv.index, y=-piv["expense"], name="Outflows", marker_color=BLUE)
            fig.add_scatter(x=piv.index, y=piv["income"] - piv["expense"], name="Net", line=dict(color=NAVY, width=2))
            fig.update_layout(barmode="relative", height=340, margin=dict(l=0, r=0, t=10, b=0),
                              xaxis_title="Week" if freq == "W" else "Day", yaxis_title="PKR", legend_orientation="h")
            st.plotly_chart(fig, width="stretch")
    with t2:
        events = fin.build_events(d, TODAY, h_end)
        proj = fin.project_cash(cash, events, TODAY, h_end)
        fig = go.Figure()
        fig.add_scatter(x=proj["date"], y=to_float(proj["balance"]), mode="lines", name="Projected balance",
                        line=dict(color=BLUE, width=3, shape="hv"))
        if reserve > 0:
            fig.add_hline(y=float(reserve), line_dash="dot", line_color=AMBER, annotation_text="Cash reserve")
        fig.add_hline(y=0, line_color=RED, line_width=1)
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Date", yaxis_title="PKR")
        st.plotly_chart(fig, width="stretch")
        st.caption("Forecast from recorded obligations and *expected* receivables (overdue receivables excluded). "
                   "It is an estimate, not a guarantee.")

    st.subheader("Recent transactions")
    show_transactions(d.transactions.sort_values("date", ascending=False).head(8))


def show_transactions(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No transactions match your filters.")
        return
    out = pd.DataFrame({"Date": [fin.fmt_date(x) for x in df["date"]], "Description": df["description"],
                        "Category": df["category"], "Type": df["type"].str.capitalize(),
                        "Amount": [money(a) for a in df["amount"]], "Status": df["status"],
                        "Counterparty": df["counterparty"]})
    st.dataframe(style_df(out, "Type", {"Income": TEAL, "Expense": RED}), width="stretch", hide_index=True)


def page_transactions(d: fin.DemoData) -> None:
    st.title("Transactions")
    banner()
    tx = d.transactions
    c = st.columns([2, 2, 1.3, 1.7])
    q = c[0].text_input("Search description or counterparty")
    rng = c[1].date_input("Date range", (TODAY - timedelta(days=60), TODAY))
    ttype = c[2].selectbox("Type", ["All", "Income", "Expense"])
    cats = sorted(tx["category"].unique()) if not tx.empty else []
    cat = c[3].multiselect("Category", cats)
    sort = st.radio("Sort by", ["Date (newest)", "Date (oldest)", "Amount (high)", "Amount (low)"], horizontal=True)

    start, end = (rng[0], rng[1]) if isinstance(rng, (tuple, list)) and len(rng) == 2 else (date.min, date.max)
    ql = q.strip().lower()
    f = fin._filter(tx, lambda r: start <= r["date"] <= end
                    and (ttype == "All" or r["type"] == ttype.lower())
                    and (not cat or r["category"] in cat)
                    and (not ql or ql in r["description"].lower() or ql in r["counterparty"].lower()))
    if not f.empty:
        key, asc = {"Date (newest)": ("date", False), "Date (oldest)": ("date", True),
                    "Amount (high)": ("amount", False), "Amount (low)": ("amount", True)}[sort]
        f = f.sort_values(key, ascending=asc)
    inc = fin.sum_money(f.loc[f["type"] == "income", "amount"]) if not f.empty else fin.ZERO
    exp = fin.sum_money(f.loc[f["type"] == "expense", "amount"]) if not f.empty else fin.ZERO
    m = st.columns(4)
    m[0].metric("Matching records", len(f))
    m[1].metric("Income", money(inc))
    m[2].metric("Expenses", money(exp))
    m[3].metric("Net", money(inc - exp))
    show_transactions(f)

    with st.expander("Add a transaction"):
        with st.form("add_txn", clear_on_submit=True):
            a, b = st.columns(2)
            desc = a.text_input("Description")
            amt = b.number_input("Amount (PKR)", min_value=0.0, step=500.0, format="%.2f")
            a, b, c2 = st.columns(3)
            dt = a.date_input("Date", TODAY, max_value=TODAY)
            tp = b.selectbox("Type", ["expense", "income"])
            cg = c2.text_input("Category", "Other")
            cp = st.text_input("Counterparty (optional)")
            if st.form_submit_button("Add transaction"):
                try:
                    st.session_state.data = fin.add_transaction(d, txn_date=dt, description=desc, category=cg,
                                                                txn_type=tp, amount=amt, counterparty=cp, today=TODAY)
                    st.success("Transaction added. Balances and charts are updated.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def page_bills(d: fin.DemoData, horizon: int) -> None:
    st.title("Bills & Receivables")
    banner()
    t1, t2 = st.tabs(["Obligations (money we owe)", "Receivables (money expected)"])
    with t1:
        ob = fin.obligations_with_status(d.obligations, TODAY)
        flt = st.radio("Show", ["Outstanding", "Overdue", "Upcoming", "Paid", "All"], horizontal=True, key="obl_f")
        rule = {"Outstanding": lambda s: s != "Paid", "Overdue": lambda s: s == "Overdue",
                "Upcoming": lambda s: s in ("Upcoming", "Due soon"), "Paid": lambda s: s == "Paid", "All": lambda s: True}[flt]
        ob = fin._filter(ob, lambda r: rule(r["status"]))
        outstanding = fin.total(fin.outstanding_obligations(d.obligations, TODAY))
        st.metric("Total outstanding obligations", money(outstanding))
        if ob.empty:
            st.info("No obligations match this filter.")
        else:
            ob = ob.sort_values("due_date")
            out = pd.DataFrame({"Description": ob["description"], "Category": ob["category"],
                                "Amount": [money(a) for a in ob["amount"]],
                                "Due date": [fin.fmt_date(x) for x in ob["due_date"]], "Status": ob["status"],
                                "Days": [("overdue by %d" % -n if n < 0 else "in %d" % n) if n is not None and n == n else "-"
                                         for n in ob["days_until_due"]]})
            st.dataframe(style_df(out, "Status", {"Overdue": RED, "Due soon": AMBER, "Paid": TEAL}),
                         width="stretch", hide_index=True)
        unpaid = fin.outstanding_obligations(d.obligations, TODAY)
        if not unpaid.empty:
            with st.form("pay_obl"):
                pick = st.selectbox("Mark an obligation as paid today", list(unpaid["id"]),
                                    format_func=lambda i: "{} – {} ({})".format(
                                        i, unpaid.set_index("id").loc[i, "description"], money(unpaid.set_index("id").loc[i, "amount"])))
                if st.form_submit_button("Mark as paid (records the expense)"):
                    try:
                        st.session_state.data = fin.mark_obligation_paid(d, pick, TODAY, today=TODAY)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
    with t2:
        rc = fin.receivables_with_status(d.receivables, TODAY)
        flt = st.radio("Show", ["Expected", "Overdue", "Received", "All"], horizontal=True, key="rec_f")
        rule = {"Expected": lambda s: s != "Received", "Overdue": lambda s: s == "Overdue",
                "Received": lambda s: s == "Received", "All": lambda s: True}[flt]
        rc = fin._filter(rc, lambda r: rule(r["status"]))
        exp_total = fin.total(fin.expected_receivables(d.receivables, TODAY, include_overdue=True))
        st.metric("Total expected receivables", money(exp_total))
        st.warning("Expected receivables are NOT cash. They only become available cash once received.")
        if rc.empty:
            st.info("No receivables match this filter.")
        else:
            rc = rc.sort_values("expected_date")
            out = pd.DataFrame({"Customer": rc["counterparty"], "Description": rc["description"],
                                "Amount": [money(a) for a in rc["amount"]],
                                "Expected date": [fin.fmt_date(x) for x in rc["expected_date"]], "Status": rc["status"]})
            st.dataframe(style_df(out, "Status", {"Overdue": RED, "Received": TEAL}),
                         width="stretch", hide_index=True)
        pending = fin._filter(d.receivables, lambda r: r["payment_status"].lower() != "received")
        if not pending.empty:
            with st.form("recv"):
                idx = pending.set_index("id")
                pick = st.selectbox("Mark a receivable as received today", list(pending["id"]),
                                    format_func=lambda i: f"{i} – {idx.loc[i, 'counterparty']} ({money(idx.loc[i, 'amount'])})")
                if st.form_submit_button("Mark as received (records the income)"):
                    try:
                        st.session_state.data = fin.mark_receivable_received(d, pick, TODAY, today=TODAY)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))


def page_simulator(d: fin.DemoData, horizon: int) -> None:
    st.title("What-If Simulator")
    banner()
    st.caption("Test a one-time purchase before you commit. All numbers come from deterministic Python calculations.")
    left, right = st.columns([1, 2.3])
    with left:
        desc = st.text_input("Purchase description", "Equipment purchase")
        amount = st.number_input("Purchase amount (PKR)", min_value=0.0, value=50000.0, step=1000.0)
        pdate = st.date_input("Planned purchase date", TODAY + timedelta(days=7), min_value=TODAY)
        reserve = st.number_input("Minimum cash reserve (PKR)", min_value=0.0, value=30000.0, step=1000.0)
        conservative = st.toggle("Conservative view (ignore expected receivables)", value=False)
    try:
        scenario = fin.Scenario(desc, Decimal(str(amount)), pdate, Decimal(str(reserve)))
        res = fin.simulate(d, scenario, TODAY, horizon, include_receivables=not conservative)
    except ValueError as exc:
        with right:
            st.error(str(exc))
        st.session_state.scenario = None
        return
    # Share the active scenario with the AI copilot.
    st.session_state.scenario = {"description": desc, "amount": str(amount), "date": pdate.isoformat(), "reserve": str(reserve)}

    with right:
        for level, msg in fin.scenario_messages(res):
            {"error": st.error, "warning": st.warning, "success": st.success, "info": st.info}[level](msg)
        c = st.columns(4)
        c[0].metric("Current available cash", money(res.current_cash))
        c[1].metric("Lowest balance (baseline)", money(res.baseline_min), help=f"on {fin.fmt_date(res.baseline_min_date)}")
        c[2].metric("Lowest balance (with purchase)", money(res.scenario_min),
                    delta=money(res.scenario_min - res.baseline_min), delta_color="inverse" if res.scenario_min < res.baseline_min else "normal",
                    help=f"on {fin.fmt_date(res.scenario_min_date)}")
        c[3].metric("Impact of purchase", money(-res.difference))

    fig = go.Figure()
    fig.add_scatter(x=res.baseline["date"], y=to_float(res.baseline["balance"]), name="Baseline",
                    line=dict(color=GREY, width=2, shape="hv"))
    fig.add_scatter(x=res.with_purchase["date"], y=to_float(res.with_purchase["balance"]), name="With purchase",
                    line=dict(color=BLUE, width=3, shape="hv"))
    fig.add_hline(y=float(res.scenario.reserve), line_dash="dot", line_color=AMBER, annotation_text="Cash reserve")
    fig.add_hline(y=0, line_color=RED, line_width=1)
    fig.add_vline(x=pd.Timestamp(pdate).timestamp() * 1000, line_dash="dash", line_color=TEAL, annotation_text="Purchase")
    fig.update_layout(height=360, margin=dict(l=0, r=0, t=20, b=0), xaxis_title="Date", yaxis_title="Projected balance (PKR)",
                      legend_orientation="h")
    st.plotly_chart(fig, width="stretch")

    table = pd.DataFrame({
        "Measure": [f"Balance on {fin.fmt_date(pdate)}", "Lowest projected balance", "Date of lowest balance",
                    f"Balance on {fin.fmt_date(res.horizon_end)}", "Below zero?", "Below reserve?"],
        "Baseline": [money(res.baseline_on_purchase_date), money(res.baseline_min), fin.fmt_date(res.baseline_min_date),
                     money(res.baseline_end), "Yes" if res.baseline_below_zero else "No", "Yes" if res.baseline_below_reserve else "No"],
        "With purchase": [money(res.scenario_on_purchase_date), money(res.scenario_min), fin.fmt_date(res.scenario_min_date),
                          money(res.scenario_end), "Yes" if res.scenario_below_zero else "No", "Yes" if res.scenario_below_reserve else "No"],
    })
    st.dataframe(table, width="stretch", hide_index=True)

    c = st.columns(2)
    c[0].metric("Obligations due by purchase date", money(res.obligations_due_by_purchase))
    c[1].metric("Expected receivables by purchase date", money(res.receivables_by_purchase),
                help="Expected, not guaranteed." if not conservative else "Excluded in conservative view.")
    with st.expander("Assumptions"):
        st.markdown(
            "- Current cash = opening balance + completed transactions (income − expenses).\n"
            "- Unpaid obligations are paid on their due date; overdue ones are assumed paid today.\n"
            "- Pending receivables arrive on their expected date; overdue receivables are excluded.\n"
            "- Paid bills and received receivables are already in current cash and are never counted twice.\n"
            "- The baseline and the scenario use identical assumptions; only the purchase differs.\n"
            "- This is a projection from simulated data, not a guarantee or professional financial advice.")
    st.info("Open **AI Financial Copilot** to have the model explain this scenario in plain language.")


EXAMPLES = ["Can I afford a PKR 50,000 equipment purchase next week?", "Which bills are due soon?",
            "Why could my cash balance fall next month?", "What happens if my biggest customer pays late?",
            "How much cash should I keep available for upcoming obligations?", "Explain my current cash-flow position.",
            "Compare the baseline with my current purchase scenario."]


def current_snapshot(d: fin.DemoData, start: date, end: date, horizon: int) -> dict:
    sc, scenario, reserve = st.session_state.scenario, None, fin.ZERO
    if sc:
        reserve = Decimal(sc["reserve"])
        scenario = fin.Scenario(sc["description"], Decimal(sc["amount"]), date.fromisoformat(sc["date"]), reserve)
    return fin.build_snapshot(d, TODAY, start, end, scenario, horizon, reserve)


def page_copilot(d: fin.DemoData, start: date, end: date, horizon: int) -> None:
    st.title("AI Financial Copilot")
    banner()
    cfg = ai.get_config()
    st.caption(f"AI-generated explanations using simulated demo data · Model: `{cfg.model}` via Groq. "
               "Figures are calculated by the app; the AI only explains them.")
    if not cfg.configured:
        st.warning("The AI is not configured yet. " + ai.SETUP_HELP + " The rest of the app works without it.")
    if st.session_state.scenario:
        sc = st.session_state.scenario
        st.info(f"Active simulator scenario: **{sc['description']}**, PKR {float(sc['amount']):,.0f} on {sc['date']}.")
    else:
        st.info("No what-if scenario yet. Run one in the What-If Simulator so the AI can discuss a specific purchase.")

    top = st.columns([4, 1])
    with top[0]:
        with st.expander("Example questions"):
            for i, q in enumerate(EXAMPLES):
                if st.button(q, key=f"ex{i}"):
                    st.session_state.chat.append({"role": "user", "content": q})
                    st.session_state.awaiting = True
                    st.rerun()
    if top[1].button("New conversation", width="stretch"):
        st.session_state.chat, st.session_state.awaiting = [], False
        st.rerun()

    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                st.caption({"ai": "AI-generated explanation", "fallback": "Rule-based summary (not AI-generated)",
                            "error": "Error"}.get(m.get("kind"), ""))

    if st.session_state.awaiting and st.session_state.chat and st.session_state.chat[-1]["role"] == "user":
        question = st.session_state.chat[-1]["content"]
        snapshot = current_snapshot(d, start, end, horizon)   # refreshed on every question
        with st.chat_message("assistant"):
            with st.spinner("Analysing your numbers..."):
                result = ai.generate_answer(question, st.session_state.chat[:-1], snapshot)
        if result.ok:
            st.session_state.chat.append({"role": "assistant", "content": result.text, "kind": "ai"})
        else:
            st.session_state.chat.append({"role": "assistant", "kind": "error", "content": f"⚠️ {result.message}"})
            st.session_state.chat.append({"role": "assistant", "kind": "fallback",
                                          "content": "**Rule-based summary** (calculated by the app, not AI):\n\n"
                                                     + ai.deterministic_summary(snapshot)})
        st.session_state.awaiting = False
        st.rerun()

    prompt = st.chat_input("Ask about your cash flow, bills or a planned purchase...")
    if prompt and prompt.strip():
        st.session_state.chat.append({"role": "user", "content": prompt.strip()})
        st.session_state.awaiting = True
        st.rerun()


# ------------------------------------------------------------------ main
def main() -> None:
    init_state()
    page, start, end, horizon, _ = sidebar()
    d = st.session_state.data
    if page == "Overview":
        page_overview(d, start, end, horizon)
    elif page == "Transactions":
        page_transactions(d)
    elif page == "Bills & Receivables":
        page_bills(d, horizon)
    elif page == "What-If Simulator":
        page_simulator(d, horizon)
    else:
        page_copilot(d, start, end, horizon)


main()
