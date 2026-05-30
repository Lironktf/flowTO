"""P03 validation harness + time-of-day factoring tests (deterministic)."""

from __future__ import annotations

from torontosim.model.timeofday import factor_daily_to_peak, peak_hour_share
from torontosim.model.validate_past import compare_predicted_observed


def test_peak_hour_shares_reasonable():
    assert 0.05 < peak_hour_share("am") < 0.15
    assert 0.05 < peak_hour_share("pm") < 0.15
    assert peak_hour_share("offpeak") < peak_hour_share("pm")


def test_factor_daily_to_peak_scales_total():
    daily = {("a", "b"): 1000.0, ("c", "d"): 500.0}
    pm = factor_daily_to_peak(daily, "pm")
    share = peak_hour_share("pm")
    assert abs(sum(pm.values()) - 1500.0 * share) < 1e-6
    # Keys preserved.
    assert set(pm) == set(daily)


def test_compare_metrics_finite_and_deterministic():
    predicted = {"e1": 0.8, "e2": 0.4, "e3": 0.6}
    observed = {"e1": 0.7, "e2": 0.5, "e3": 0.6}
    m1 = compare_predicted_observed(predicted, observed)
    m2 = compare_predicted_observed(predicted, observed)
    assert m1 == m2
    assert m1["n"] == 3
    assert m1["mae"] >= 0 and m1["mae"] == m1["mae"]  # finite
    assert 0 <= m1["pct_error"] < 100


def test_compare_ignores_unmatched_keys():
    predicted = {"e1": 1.0, "only_pred": 5.0}
    observed = {"e1": 1.0, "only_obs": 9.0}
    m = compare_predicted_observed(predicted, observed)
    assert m["n"] == 1  # only e1 is matched
    assert m["mae"] == 0.0
