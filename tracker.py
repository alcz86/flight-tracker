"""Tracker cen lotów do Tromsø.

Sprawdza w Google Flights loty w jedną stronę z każdego lotniska z config.json
do Tromsø i z powrotem, łączy je w pary dające 2–3 pełne dni na miejscu
i zapisuje najtańsze opcje do REPORT.md oraz historię do data/history.csv.
"""

from __future__ import annotations

import csv
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "state.json"
HISTORY_FILE = DATA_DIR / "history.csv"
TRIPS_FILE = DATA_DIR / "trips_latest.csv"
REPORT_FILE = ROOT / "REPORT.md"
ALERT_FILE = ROOT / "alert.md"


@dataclass
class Leg:
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    price: int
    airlines: list[str]
    stops: int
    url: str


@dataclass
class Trip:
    origin: str
    outbound: Leg
    inbound: Leg
    full_days: int

    @property
    def total(self) -> int:
        return self.outbound.price + self.inbound.price

    @property
    def nights(self) -> int:
        return (self.inbound.departure.date() - self.outbound.arrival.date()).days

    def dates(self) -> str:
        return f"{self.outbound.departure:%d.%m} → {self.inbound.departure:%d.%m}"


def load_config(path: Path = ROOT / "config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def daterange(start: str, end: str):
    d = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while d <= stop:
        yield d
        d += timedelta(days=1)


def full_days(arrival: datetime, departure: datetime, cfg: dict) -> int:
    """Liczba pełnych dni na miejscu między przylotem a wylotem powrotnym."""
    first = arrival.date()
    if arrival.hour >= cfg["full_day_if_arrival_before_hour"]:
        first += timedelta(days=1)
    last = departure.date()
    if departure.hour < cfg["full_day_if_departure_after_hour"]:
        last -= timedelta(days=1)
    return max(0, (last - first).days + 1)


def build_query(origin: str, destination: str, day: date, cfg: dict):
    from fast_flights import FlightQuery, Passengers, create_query

    pax = cfg["passengers"]
    return create_query(
        flights=[FlightQuery(date=day.isoformat(), from_airport=origin, to_airport=destination)],
        trip="one-way",
        passengers=Passengers(adults=pax.get("adults", 0), children=pax.get("children", 0)),
        currency=cfg["currency"],
        language="en",
        max_stops=cfg["max_stops"],
        carry_on_bags=cfg["carry_on_bags"],
    )


def fetch_legs(origin: str, destination: str, day: date, cfg: dict) -> list[Leg]:
    """Pobiera loty z Google Flights. Pusta lista, gdy brak lotów."""
    from fast_flights import FlightsNotFound, get_flights

    query = build_query(origin, destination, day, cfg)
    url = query.url()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            results = get_flights(query)
            break
        except FlightsNotFound:
            return []
        except TypeError:
            # fast-flights tak reaguje na odpowiedź Google bez żadnych lotów
            # (np. brak połączeń z dozwoloną liczbą przesiadek) — ponawianie nic nie da
            return []
        except Exception as e:  # zmiana HTML, blokada, timeout
            last_error = e
            time.sleep(5 * (attempt + 1))
    else:
        print(f"  ! {origin}->{destination} {day}: {last_error!r}", file=sys.stderr)
        return []

    legs = []
    for r in results:
        if not r.flights or not r.price:
            continue
        first, last = r.flights[0], r.flights[-1]
        try:
            legs.append(
                Leg(
                    origin=origin,
                    destination=destination,
                    departure=datetime(*first.departure.date, *first.departure.time),
                    arrival=datetime(*last.arrival.date, *last.arrival.time),
                    price=int(r.price),
                    airlines=list(r.airlines),
                    stops=len(r.flights) - 1,
                    url=url,
                )
            )
        except (TypeError, ValueError) as e:  # niekompletne dane jednego lotu
            print(f"  ! {origin}->{destination} {day}: pominięto lot ({e!r})", file=sys.stderr)
    return legs


def combine(origin: str, outbound: list[Leg], inbound: list[Leg], cfg: dict) -> list[Trip]:
    trips = []
    for o in outbound:
        for i in inbound:
            if i.departure <= o.arrival:
                continue
            days = full_days(o.arrival, i.departure, cfg)
            if cfg["min_full_days"] <= days <= cfg["max_full_days"]:
                trips.append(Trip(origin, o, i, days))
    trips.sort(key=lambda t: (t.total, -t.full_days))
    return trips


def pick_recommendation(best_by_origin: dict[str, Trip], origins: list[str], tolerance_pct: float) -> Trip | None:
    """Wybiera lotnisko wg priorytetu; niższy priorytet wygrywa tylko,
    gdy jest tańszy o więcej niż tolerance_pct."""
    choice = None
    for code in origins:
        trip = best_by_origin.get(code)
        if trip is None:
            continue
        if choice is None or trip.total < choice.total * (1 - tolerance_pct / 100):
            choice = trip
    return choice


def find_alerts(
    best_by_origin: dict[str, Trip], previous: dict[str, int], cfg: dict, below_alerted: dict | None = None
) -> list[str]:
    """Alerty o spadku ceny i o cenie poniżej progu.

    below_alerted (lotnisko -> najniższa cena, o której już powiadomiono poniżej progu)
    jest aktualizowane w miejscu. Dzięki temu chwilowe zniknięcie lotu z wyników
    Google nie powoduje ponownego alertu o tej samej cenie.
    """
    alerts = []
    below_alerted = {} if below_alerted is None else below_alerted
    threshold = cfg.get("alert_below_total_pln")
    drop_pct = cfg.get("alert_drop_pct")
    for code, trip in best_by_origin.items():
        if threshold and trip.total < threshold and trip.total < below_alerted.get(code, threshold):
            alerts.append(
                f"{code}: cena poniżej {threshold} {cfg['currency']} — {trip.total} {cfg['currency']} "
                f"({trip.dates()}, {trip.nights} noce, {trip.full_days} pełne dni)"
            )
            below_alerted[code] = trip.total
            continue
        old = previous.get(code)
        if drop_pct and old is not None and trip.total <= old * (1 - drop_pct / 100):
            alerts.append(
                f"{code}: cena spadła z {old} do {trip.total} {cfg['currency']} "
                f"({trip.dates()}, {trip.nights} noce, {trip.full_days} pełne dni)"
            )
    return alerts


def fmt_leg(leg: Leg) -> str:
    stops = "bezpośredni" if leg.stops == 0 else f"{leg.stops} przesiadka"
    return (
        f"{leg.departure:%a %d.%m %H:%M} → {leg.arrival:%H:%M} "
        f"({', '.join(leg.airlines)}, {stops}) — {leg.price} zł"
    )


def _days_range(cfg: dict) -> str:
    lo, hi = cfg["min_full_days"], cfg["max_full_days"]
    return str(lo) if lo == hi else f"{lo}–{hi}"


def render_report(cfg, names, trips_by_origin, recommendation, errors, now, cheapest=None) -> str:
    cur = cfg["currency"]
    pax = cfg["passengers"]
    lines = [
        "# Tracker lotów do Tromsø",
        "",
        f"Ostatnie sprawdzenie: **{now:%Y-%m-%d %H:%M} UTC**  ",
        f"Okres: {cfg['date_from']} – {cfg['date_to']}, "
        f"{pax.get('adults', 0)} dorosłych + {pax.get('children', 0)} dziecko, "
        f"bagaż podręczny: {cfg['carry_on_bags']}, "
        f"{_days_range(cfg)} pełne dni na miejscu, preferowane {cfg.get('preferred_min_nights', 0)}+ noce.  ",
        "Ceny to łączny koszt dla całej grupy (Google Flights, z szacunkiem opłat za bagaż podręczny).",
        "",
    ]
    if recommendation:
        r = recommendation
        lines += [
            "## Polecana opcja",
            "",
            f"**{names[r.origin]} ({r.origin}) — {r.total} {cur}**, {r.nights} noce, {r.full_days} pełne dni",
            "",
            f"- Tam: {fmt_leg(r.outbound)} — [Google Flights]({r.outbound.url})",
            f"- Powrót: {fmt_leg(r.inbound)} — [Google Flights]({r.inbound.url})",
            "",
        ]
        if cheapest and cheapest.total < r.total:
            c = cheapest
            lines += [
                f"Najtańsza ogółem (krótszy pobyt): {names[c.origin]} — **{c.total} {cur}**, "
                f"{c.dates()}, {c.nights} noce, {c.full_days} pełne dni.",
                "",
            ]
    else:
        lines += ["## Brak pasujących lotów", ""]

    for code, trips in trips_by_origin.items():
        lines += [f"## {names[code]} ({code})", ""]
        if not trips:
            lines += ["Brak połączeń spełniających warunki.", ""]
            continue
        lines += ["| Cena | Noce | Pełne dni | Tam | Powrót |", "|---|---|---|---|---|"]
        for t in trips[: cfg["top_n"]]:
            lines.append(
                f"| **{t.total} {cur}** | {t.nights} | {t.full_days} | [{fmt_leg(t.outbound)}]({t.outbound.url}) "
                f"| [{fmt_leg(t.inbound)}]({t.inbound.url}) |"
            )
        lines.append("")
        # trips są posortowane po cenie, więc pierwsza pasująca para jest najtańsza
        for n in sorted({t.nights for t in trips}):
            best_n = next(t for t in trips if t.nights == n)
            lines.append(
                f"- Najtaniej na {n} noce ({best_n.full_days} pełne dni): **{best_n.total} {cur}** — "
                f"tam {fmt_leg(best_n.outbound)}, powrót {fmt_leg(best_n.inbound)}"
            )
        lines.append("")

    if errors:
        lines += ["## Problemy z pobieraniem", "", *[f"- {e}" for e in errors], ""]
    return "\n".join(lines)


def run(cfg: dict, fetch=fetch_legs, sleep=time.sleep, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    dest = cfg["destination"]
    codes = [o["code"] for o in cfg["origins"]]
    names = {o["code"]: o["name"] for o in cfg["origins"]}
    days = list(daterange(cfg["date_from"], cfg["date_to"]))

    trips_by_origin: dict[str, list[Trip]] = {}
    errors = []
    for code in codes:
        print(f"Sprawdzam {code} <-> {dest}...")
        outbound, inbound = [], []
        for d in days:
            outbound += fetch(code, dest, d, cfg)
            sleep(cfg["request_delay_seconds"] + random.random())
            inbound += fetch(dest, code, d, cfg)
            sleep(cfg["request_delay_seconds"] + random.random())
        if not outbound and not inbound:
            errors.append(f"{code}: brak jakichkolwiek wyników (blokada Google lub brak lotów)")
        trips_by_origin[code] = combine(code, outbound, inbound, cfg)

    best = {c: t[0] for c, t in trips_by_origin.items() if t}
    # polecamy opcję z preferowaną liczbą nocy; krótsze tylko, gdy takiej nie ma
    min_nights = cfg.get("preferred_min_nights", 0)
    preferred = {
        c: p for c, t in trips_by_origin.items() if (p := next((x for x in t if x.nights >= min_nights), None))
    }
    tol = cfg["priority_tolerance_pct"]
    recommendation = pick_recommendation(preferred, codes, tol) or pick_recommendation(best, codes, tol)
    cheapest = min(best.values(), key=lambda t: t.total, default=None)

    DATA_DIR.mkdir(exist_ok=True)
    previous = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    below_alerted = previous.pop("below_alerted", {})
    below_alerted_pref = previous.pop("below_alerted_preferred", {})
    alerts = find_alerts(best, previous, cfg, below_alerted)
    # osobny alert progu dla preferowanej długości pobytu: tańsza krótsza opcja
    # nie może zagłuszyć spadku ceny opcji z preferowaną liczbą nocy
    if min_nights:
        pref_cfg = {**cfg, "alert_drop_pct": None}
        alerts += [f"[{min_nights}+ noce] {a}" for a in find_alerts(preferred, {}, pref_cfg, below_alerted_pref)]
    # nie nadpisuj stanu lotniska, dla którego tym razem nic nie pobrano
    state = {
        **previous,
        **{c: t.total for c, t in best.items()},
        "below_alerted": below_alerted,
        "below_alerted_preferred": below_alerted_pref,
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))

    new_file = not HISTORY_FILE.exists()
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["checked_at", "origin", "total", "outbound", "inbound", "full_days", "airlines"])
        for c, t in best.items():
            w.writerow([
                now.isoformat(timespec="minutes"), c, t.total,
                t.outbound.departure.isoformat(timespec="minutes"),
                t.inbound.departure.isoformat(timespec="minutes"),
                t.full_days, "/".join(sorted(set(t.outbound.airlines + t.inbound.airlines))),
            ])

    with open(TRIPS_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["origin", "total", "full_days", "outbound", "outbound_price",
                    "inbound", "inbound_price", "airlines", "stops"])
        for c, trips in trips_by_origin.items():
            for t in trips:
                w.writerow([
                    c, t.total, t.full_days,
                    t.outbound.departure.isoformat(timespec="minutes"), t.outbound.price,
                    t.inbound.departure.isoformat(timespec="minutes"), t.inbound.price,
                    "/".join(sorted(set(t.outbound.airlines + t.inbound.airlines))),
                    f"{t.outbound.stops}+{t.inbound.stops}",
                ])

    report = render_report(cfg, names, trips_by_origin, recommendation, errors, now, cheapest)
    REPORT_FILE.write_text(report, encoding="utf-8")

    if alerts:
        ALERT_FILE.write_text(
            "\n".join(["Zmiana cen lotów do Tromsø:", "", *[f"- {a}" for a in alerts], "", report]),
            encoding="utf-8",
        )
    elif ALERT_FILE.exists():
        ALERT_FILE.unlink()

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"alert={'true' if alerts else 'false'}\n")

    print(report)
    return {"best": best, "recommendation": recommendation, "alerts": alerts}


if __name__ == "__main__":
    result = run(load_config())
    if not result["best"]:
        # błąd joba => GitHub wyśle mail, że tracker przestał dostawać dane
        sys.exit("Nie znaleziono żadnej pary lotów — sprawdź sekcję „Problemy z pobieraniem” w REPORT.md")
