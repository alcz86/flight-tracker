# Tracker lotów do Tromsø

Trzy razy dziennie (GitHub Actions, ok. 7:17, 13:17 i 19:17) sprawdza w Google Flights ceny lotów do Tromsø w marcu 2027
dla 4 dorosłych i 1 dziecka z bagażem podręcznym. Interesują go tylko pary lotów,
które dają 2–3 pełne dni na miejscu.

Lotniska według priorytetu: **Katowice → Kraków → Gdańsk**. Lotnisko z niższym priorytetem
jest polecane tylko wtedy, gdy jest tańsze o ponad 15% (`priority_tolerance_pct`).

## Co dostajesz

- `REPORT.md` – najtańsze opcje dla każdego lotniska i polecana opcja, z linkami do Google Flights.
- `data/history.csv` – historia najlepszej ceny z każdego sprawdzenia.
- Powiadomienie: issue „Tracker lotów do Tromsø” z oznaczeniem właściciela repo
  (GitHub wysyła mail), gdy cena spadnie o ≥5% (`alert_drop_pct`)
  albo pierwszy raz zejdzie poniżej 5000 zł (`alert_below_total_pln`).
- Gdy żadne lotnisko nie zwróci wyników (np. Google zablokuje zapytania), job kończy się
  błędem i GitHub wysyła mail o nieudanym workflow.

## Uruchomienie

- Harmonogram działa dopiero po scaleniu do domyślnej gałęzi repo.
- Ręcznie: zakładka **Actions → Flight tracker Tromsø → Run workflow**.
- Częstotliwość: `cron` w `.github/workflows/flight-tracker.yml` (godziny w UTC).
- Lokalnie: `pip install -r requirements.txt && python tracker.py`.
- Testy: `pip install pytest && python -m pytest tests`.

## Jak liczone są pełne dni

Dzień przylotu liczy się jako pełny, gdy przylot jest przed 10:00, a dzień wylotu,
gdy wylot jest po 20:00. Godziny można zmienić w `config.json`.

## Ograniczenia

- Dane pochodzą ze scrapera Google Flights (`fast-flights`), bez oficjalnego API.
  Gdy Google zmieni stronę albo zablokuje zapytania, raport pokaże sekcję „Problemy z pobieraniem”.
- Opłata za bagaż podręczny jest szacunkiem Google. Cenę i dopłatę (np. WIZZ Priority)
  zawsze sprawdź u przewoźnika przed zakupem.
- Pary lotów to dwa osobne bilety w jedną stronę. W tanich liniach cena jest taka sama
  jak przy bilecie w obie strony, ale przy przesiadkach zwykle nie ma ochrony połączenia.
