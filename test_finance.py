"""Tests use small deterministic data with hand-calculated answers.

TODAY = 2026-10-10, opening balance 100,000.
Completed transactions: +50,000 income, -20,000 expense  -> current cash 130,000.
Obligations: A 30,000 (+3d), B 10,000 (+10d), C 5,000 PAID, D 2,000 overdue (-1d, counted today).
Receivables: R1 20,000 (+5d), R2 8,000 RECEIVED, R3 4,000 overdue (excluded by default).
Baseline (30d): day0 128,000 -> day3 98,000 -> day5 118,000 -> day10 108,000.
"""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

import finance as f

TODAY = date(2026, 10, 10)


def day(n):
    return TODAY + timedelta(days=n)


@pytest.fixture
def data():
    return f.build_data(
        transactions=[
            {"id": "T001", "date": day(-5), "description": "Sale", "category": "Sales", "type": "income", "amount": 50000},
            {"id": "T002", "date": day(-3), "description": "Stock", "category": "Supplier", "type": "expense", "amount": 20000},
            {"id": "T003", "date": day(-2), "description": "Pending sale", "category": "Sales", "type": "income",
             "amount": 999, "status": "Pending"},
        ],
        obligations=[
            {"id": "O1", "description": "A", "category": "Supplier", "amount": 30000, "due_date": day(3)},
            {"id": "O2", "description": "B", "category": "Rent", "amount": 10000, "due_date": day(10)},
            {"id": "O3", "description": "C", "category": "Utilities", "amount": 5000, "due_date": day(-2), "payment_status": "Paid"},
            {"id": "O4", "description": "D", "category": "Utilities", "amount": 2000, "due_date": day(-1)},
        ],
        receivables=[
            {"id": "R1", "description": "Inv 1", "counterparty": "X", "amount": 20000, "expected_date": day(5)},
            {"id": "R2", "description": "Inv 2", "counterparty": "Y", "amount": 8000, "expected_date": day(-4), "payment_status": "Received"},
            {"id": "R3", "description": "Inv 3", "counterparty": "Z", "amount": 4000, "expected_date": day(-2)},
        ],
        opening_balance=100000,
    )


def scen(amount=60000, offset=7, reserve=0):
    return f.Scenario("Equipment", D(amount), day(offset), D(reserve))


def test_current_balance_ignores_pending_transactions(data):
    assert f.current_cash(data.transactions, data.opening_balance, TODAY) == D("130000")


def test_income_and_expense_totals(data):
    t = f.period_totals(data.transactions, day(-30), TODAY)
    assert (t["income"], t["expenses"], t["net"]) == (D("50000"), D("20000"), D("30000"))


def test_period_totals_across_month_boundary():
    d = f.build_data(transactions=[
        {"id": "T1", "date": date(2026, 9, 29), "description": "a", "category": "c", "type": "income", "amount": 100},
        {"id": "T2", "date": date(2026, 10, 2), "description": "b", "category": "c", "type": "income", "amount": 50},
        {"id": "T3", "date": date(2026, 11, 1), "description": "c", "category": "c", "type": "income", "amount": 7}])
    assert f.period_totals(d.transactions, date(2026, 9, 25), date(2026, 10, 5))["income"] == D("150")


def test_outstanding_obligations_total_and_paid_excluded(data):
    out = f.outstanding_obligations(data.obligations, TODAY)
    assert set(out["id"]) == {"O1", "O2", "O4"}          # O3 is paid
    assert f.total(out) == D("42000")
    assert f.total(f.outstanding_obligations(data.obligations, TODAY, day(7))) == D("32000")


def test_received_and_overdue_receivables_excluded_from_expected(data):
    rec = f.expected_receivables(data.receivables, TODAY)
    assert list(rec["id"]) == ["R1"]
    assert f.total(f.expected_receivables(data.receivables, TODAY, include_overdue=True)) == D("24000")


def test_statuses_derived_from_payment_and_date(data):
    s = f.obligations_with_status(data.obligations, TODAY).set_index("id")["status"]
    assert (s["O1"], s["O2"], s["O3"], s["O4"]) == ("Due soon", "Upcoming", "Paid", "Overdue")


def test_baseline_projection(data):
    cash = f.current_cash(data.transactions, data.opening_balance, TODAY)
    base = f.project_cash(cash, f.build_events(data, TODAY, day(30)), TODAY, day(30))
    assert f.balance_on(base, TODAY) == D("128000")      # overdue bill D counted today
    assert f.balance_on(base, day(3)) == D("98000")
    assert f.balance_on(base, day(5)) == D("118000")
    assert f.balance_on(base, day(30)) == D("108000")
    assert f.lowest_point(base) == (D("98000"), day(3))


def test_scenario_projection_and_difference(data):
    r = f.simulate(data, scen(60000, 7), TODAY, 30)
    assert r.baseline_on_purchase_date == D("118000")
    assert r.scenario_on_purchase_date == D("58000")
    assert r.baseline_end - r.scenario_end == D("60000") == r.difference
    assert (r.scenario_min, r.scenario_min_date) == (D("48000"), day(10))


def test_baseline_unchanged_by_scenario_and_same_assumptions(data):
    r = f.simulate(data, scen(60000, 7), TODAY, 30)
    cash = f.current_cash(data.transactions, data.opening_balance, TODAY)
    expected = f.project_cash(cash, f.build_events(data, TODAY, day(30)), TODAY, day(30))
    assert list(r.baseline["balance"]) == list(expected["balance"])
    # before the purchase date, both projections are identical
    assert list(r.baseline["balance"][:7]) == list(r.with_purchase["balance"][:7])


def test_future_dated_purchase_only_affects_later_days(data):
    r = f.simulate(data, scen(1000, 20), TODAY, 30)
    assert f.balance_on(r.with_purchase, day(19)) == f.balance_on(r.baseline, day(19))
    assert f.balance_on(r.with_purchase, day(20)) == f.balance_on(r.baseline, day(20)) - D("1000")


def test_negative_balance_detected(data):
    r = f.simulate(data, scen(150000, 7), TODAY, 30)
    assert r.scenario_below_zero and r.first_shortfall_date == day(7)
    assert not r.baseline_below_zero
    assert f.scenario_messages(r)[0][0] == "error"


def test_reserve_breach_detected(data):
    r = f.simulate(data, scen(60000, 7, reserve=50000), TODAY, 30)
    assert r.scenario_below_reserve and not r.scenario_below_zero
    assert f.scenario_messages(r)[0][0] == "warning"
    ok = f.simulate(data, scen(60000, 7, reserve=40000), TODAY, 30)
    assert not ok.scenario_below_reserve and f.scenario_messages(ok)[0][0] == "success"


def test_conservative_view_excludes_receivables(data):
    r = f.simulate(data, scen(60000, 7), TODAY, 30, include_receivables=False)
    assert f.balance_on(r.baseline, day(30)) == D("88000")   # 130,000 - 42,000
    assert r.receivables_by_purchase == D("0")


@pytest.mark.parametrize("kwargs", [dict(amount=0), dict(amount=-5), dict(offset=-1), dict(reserve=-1)])
def test_invalid_scenarios_rejected(data, kwargs):
    with pytest.raises(ValueError):
        f.simulate(data, scen(**{"amount": 100, **kwargs}), TODAY)


def test_empty_and_missing_data_do_not_crash():
    d = f.build_data()
    assert f.current_cash(d.transactions, d.opening_balance, TODAY) == D("0")
    assert f.period_totals(d.transactions, day(-30), TODAY)["net"] == D("0")
    r = f.simulate(d, scen(100, 3), TODAY)
    assert r.scenario_below_zero and r.baseline_min == D("0")
    assert f.generate_insights(d, TODAY) == [] or isinstance(f.generate_insights(d, TODAY), list)
    snap = f.build_snapshot(d, TODAY, day(-30), TODAY, scen(100, 3))
    assert snap["current_available_cash"]["amount"] == "0.00"


def test_add_transaction_validation_and_duplicates(data):
    kw = dict(txn_date=day(-1), description="Tea", category="Office", txn_type="expense", amount=500, today=TODAY)
    d2 = f.add_transaction(data, **kw)
    assert f.current_cash(d2.transactions, d2.opening_balance, TODAY) == D("129500")
    with pytest.raises(ValueError):
        f.add_transaction(d2, **kw)                       # duplicate submission
    with pytest.raises(ValueError):
        f.add_transaction(data, **{**kw, "amount": 0})
    with pytest.raises(ValueError):
        f.add_transaction(data, **{**kw, "txn_date": day(2)})
    with pytest.raises(ValueError):
        f.add_transaction(data, **{**kw, "txn_type": "refund"})


def test_marking_paid_never_double_counts(data):
    d2 = f.mark_obligation_paid(data, "O1", TODAY, today=TODAY)
    assert f.current_cash(d2.transactions, d2.opening_balance, TODAY) == D("100000")      # 130,000 - 30,000
    assert "O1" not in set(f.outstanding_obligations(d2.obligations, TODAY)["id"])
    r = f.simulate(d2, scen(1000, 7), TODAY)
    assert r.baseline_end == D("100000") - D("12000") + D("20000")                        # B + D still due, R1 still expected
    with pytest.raises(ValueError):
        f.mark_obligation_paid(d2, "O1", TODAY, today=TODAY)

    d3 = f.mark_receivable_received(data, "R1", TODAY, today=TODAY)
    assert f.current_cash(d3.transactions, d3.opening_balance, TODAY) == D("150000")
    assert f.expected_receivables(d3.receivables, TODAY).empty


def test_sample_data_loads_and_tells_the_demo_story():
    d = f.load_sample_data(TODAY)
    assert f.current_cash(d.transactions, d.opening_balance, TODAY) == D("200000")
    s = f.Scenario("Equipment purchase", D(50000), day(7), D(30000))
    with_rec = f.simulate(d, s, TODAY, 30, True)
    without = f.simulate(d, s, TODAY, 30, False)
    assert not with_rec.scenario_below_zero and with_rec.scenario_below_reserve
    assert without.scenario_below_zero


def test_snapshot_matches_simulation(data):
    s = scen(60000, 7, 50000)
    snap = f.build_snapshot(data, TODAY, day(-30), TODAY, s, 30, D(50000))
    r = f.simulate(data, s, TODAY, 30)
    assert snap["current_available_cash"]["amount"] == str(r.current_cash)
    assert snap["active_scenario"]["scenario_lowest_balance"]["amount"] == str(r.scenario_min)
    assert snap["active_scenario"]["breaches_minimum_reserve"] is True
    assert snap["active_scenario_if_expected_receivables_never_arrive"]["includes_expected_receivables"] is False
    assert f.build_snapshot(data, TODAY, day(-30), TODAY)["active_scenario"] is None
