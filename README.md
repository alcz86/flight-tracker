# Tracker lotów do Tromsø

Co 2 godziny (GitHub Actions) sprawdza w Google Flights ceny lotów do Tromsø w marcu 2027
dla 4 dorosłych i 1 dziecka z bagażem podręcznym. Interesują go tylko pary lotów,
które dają 2–3 pełne dni na miejscu. Preferowane są 3 noce: polecana opcja
to najtańsza z co najmniej 3 nocami (`preferred_min_nights`), a 2 noce tylko gdy
wylot powrotny jest po południu.

Lotniska według priorytetu: **Katowice → Kraków → Gdańsk**. Lotnisko z niższym priorytetem
jest polecane tylko wtedy, gdy jest tańsze o ponad 15% (`priority_tolerance_pct`).

## Co dostajesz

- `REPORT.md` – najtańsze opcje dla każdego lotniska i polecana opcja, z linkami do Google Flights.
- `data/history.csv` – historia najlepszej ceny z każdego sprawdzenia.
- Powiadomienie: issue „Tracker lotów do Tromsø” z oznaczeniem właściciela repo
  (GitHub wysyła mail), gdy najtańsza opcja z któregoś lotniska spadnie poniżej
  2000 zł (`alert_below_total_pln`). Kolejny alert przychodzi tylko przy jeszcze niższej cenie.
  Osobny alert „[3+ noce]” przychodzi, gdy poniżej progu spadnie opcja z preferowaną
  liczbą nocy, nawet jeśli krótszy pobyt jest jeszcze tańszy.
  Alerty o każdym spadku ceny (`alert_drop_pct`) są wyłączone (`null`), bo Google
  czasem chwilowo nie pokazuje lotu i dawało to fałszywe alarmy.
- `data/trips_latest.csv` – wszystkie pary lotów z ostatniego sprawdzenia.
- Gdy żadne lotnisko nie zwróci wyników (np. Google zablokuje zapytania), job kończy się
  błędem i GitHub wysyła mail o nieudanym workflow.

## Uruchomienie

- Harmonogram działa dopiero po scaleniu do domyślnej gałęzi repo.
- Ręcznie: zakładka **Actions → Flight tracker Tromsø → Run workflow**.
- Częstotliwość: `cron` w `.github/workflows/flight-tracker.yml` (godziny w UTC).
- Lokalnie: `pip install -r requirements.txt && python tracker.py`.
- Testy: `pip install pytest && python -m pytest tests`.

## Jak liczone są pełne dni

Dzień przylotu nigdy nie liczy się jako pełny. Dzień wylotu liczy się, gdy wylot
jest od 12:00. Przykład: przylot 7.03, wylot 10.03 o 15:00 → pełne 8, 9 i 10.03;
przy wylocie 10.03 rano pełne są tylko 8 i 9.03.
Ustawienia: `full_day_if_arrival_before_hour: 0` i `full_day_if_departure_after_hour: 12`
w `config.json`.

## Ograniczenia

- Dane pochodzą ze scrapera Google Flights (`fast-flights`), bez oficjalnego API.
  Gdy Google zmieni stronę albo zablokuje zapytania, raport pokaże sekcję „Problemy z pobieraniem”.
- Opłata za bagaż podręczny jest szacunkiem Google. Cenę i dopłatę (np. WIZZ Priority)
  zawsze sprawdź u przewoźnika przed zakupem.
- Pary lotów to dwa osobne bilety w jedną stronę. W tanich liniach cena jest taka sama
  jak przy bilecie w obie strony, ale przy przesiadkach zwykle nie ma ochrony połączenia.
