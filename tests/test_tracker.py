import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tracker  # noqa: E402

CFG = {
    **tracker.load_config(),
    "date_from": "2027-03-05",
    "date_to": "2027-03-09",
    "request_delay_seconds": 0,
}


def leg(o, d, dep, arr, price):
    return tracker.Leg(o, d, dep, arr, price, ["Wizz Air"], 0, "https://example.com")


def test_full_days_evening_arrival_and_afternoon_departure():
    # przylot pt wieczorem, wylot pon po południu -> sob + nd
    assert tracker.full_days(datetime(2027, 3, 5, 18), datetime(2027, 3, 8, 15), CFG) == 2


def test_full_days_counts_early_arrival_and_late_departure():
    assert tracker.full_days(datetime(2027, 3, 5, 8), datetime(2027, 3, 7, 21), CFG) == 3


def test_full_days_never_negative():
    assert tracker.full_days(datetime(2027, 3, 5, 18), datetime(2027, 3, 6, 9), CFG) == 0


def test_combine_filters_by_full_days_and_sorts_by_price():
    out = [leg("KTW", "TOS", datetime(2027, 3, 5, 6), datetime(2027, 3, 5, 12), 1000)]
    back = [
        leg("TOS", "KTW", datetime(2027, 3, 6, 15), datetime(2027, 3, 6, 18), 100),   # 0 dni
        leg("TOS", "KTW", datetime(2027, 3, 8, 15), datetime(2027, 3, 8, 18), 900),   # 2 dni
        leg("TOS", "KTW", datetime(2027, 3, 9, 15), datetime(2027, 3, 9, 18), 800),   # 3 dni
        leg("TOS", "KTW", datetime(2027, 3, 12, 15), datetime(2027, 3, 12, 18), 50),  # 6 dni
    ]
    trips = tracker.combine("KTW", out, back, CFG)
    assert [(t.total, t.full_days) for t in trips] == [(1800, 3), (1900, 2)]


def _trip(origin, total):
    o = leg(origin, "TOS", datetime(2027, 3, 5, 6), datetime(2027, 3, 5, 12), total)
    i = leg("TOS", origin, datetime(2027, 3, 8, 15), datetime(2027, 3, 8, 18), 0)
    return tracker.Trip(origin, o, i, 2)


def test_priority_keeps_katowice_unless_other_much_cheaper():
    codes = ["KTW", "KRK", "GDN"]
    best = {"KTW": _trip("KTW", 4000), "KRK": _trip("KRK", 3700), "GDN": _trip("GDN", 3000)}
    assert tracker.pick_recommendation(best, codes, 15).origin == "GDN"
    best["GDN"] = _trip("GDN", 3500)
    assert tracker.pick_recommendation(best, codes, 15).origin == "KTW"
    del best["KTW"]
    assert tracker.pick_recommendation(best, codes, 15).origin == "KRK"


def test_alerts_on_drop_and_threshold():
    best = {"KTW": _trip("KTW", 4500), "KRK": _trip("KRK", 6000), "GDN": _trip("GDN", 4950)}
    alerts = tracker.find_alerts(best, {"KTW": 4800, "KRK": 6100, "GDN": 5100}, CFG)
    assert alerts == ["KTW: cena spadła z 4800 do 4500 PLN", "GDN: cena poniżej progu 5000 — 4950 PLN"]
    assert tracker.find_alerts(best, {}, CFG) == []


def test_run_end_to_end(tmp_path, monkeypatch):
    for name, fname in [("DATA_DIR", "data"), ("REPORT_FILE", "REPORT.md"), ("ALERT_FILE", "alert.md")]:
        monkeypatch.setattr(tracker, name, tmp_path / fname)
    monkeypatch.setattr(tracker, "STATE_FILE", tmp_path / "data" / "state.json")
    monkeypatch.setattr(tracker, "HISTORY_FILE", tmp_path / "data" / "history.csv")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    prices = {"KTW": 800, "KRK": 700, "GDN": 300}

    def fake_fetch(o, d, day: date, cfg):
        if o == "TOS":
            return [leg(o, d, datetime(day.year, day.month, day.day, 16),
                        datetime(day.year, day.month, day.day, 19), prices[d])]
        if day.weekday() != 4:  # tylko piątki tam
            return []
        return [leg(o, d, datetime(day.year, day.month, day.day, 9),
                    datetime(day.year, day.month, day.day, 13), prices[o])]

    result = tracker.run(CFG, fetch=fake_fetch, sleep=lambda s: None, now=datetime(2026, 10, 5))
    assert result["best"]["KTW"].total == 1600
    assert result["recommendation"].origin == "GDN"
    assert "Polecana opcja" in (tmp_path / "REPORT.md").read_text()
    assert json.loads((tmp_path / "data" / "state.json").read_text())["KTW"] == 1600

    prices["KTW"] = 500
    result = tracker.run(CFG, fetch=fake_fetch, sleep=lambda s: None, now=datetime(2026, 10, 6))
    assert result["alerts"] and (tmp_path / "alert.md").exists()
