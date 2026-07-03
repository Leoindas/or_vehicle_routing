"""Schritt ③ der Datenpipeline: Geokoordinaten -> Zeit-/Distanzmatrix.

Fragt für jedes Adresspaar bei einem **lokalen OSRM-Server** (siehe README,
unter Linux mit `germany-latest.osm.pbf` aufgesetzt) die Fahrzeit und die
Straßen-Distanz ab. Die Abfragen laufen parallel über einen Thread-Pool mit
Retry-Logik, weil bei n Adressen n·(n−1) Anfragen anfallen (z. B. 213 Adressen
≈ 45 000 Anfragen). Ergebnis: eine Excel-Datei mit den Blättern `Zeitmatrix`
(Sekunden) und `Distanzmatrix` (Meter) – die Eingabe für die Optimierungs-App.

Voraussetzung: laufender OSRM-Server auf http://localhost:5000
(Aufsetzen siehe README, Abschnitt „Datenpipeline“).

Einmaliger Vorlauf – für den Betrieb der App nicht erneut nötig.
"""

import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import os
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

# Logging konfigurieren
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(message)s')

# Parameter
excel_datei = "geokodierte_adressen.xlsx"  # Pfad zur Excel-Datei

# Lade die Excel-Datei
df = pd.read_excel(excel_datei)

# Überprüfe die verfügbaren Spaltennamen
print("Verfügbare Spalten:", df.columns)

# Ersetze Kommas durch Punkte und konvertiere zu float
df['latitude'] = df['latitude'].astype(str).str.replace(',', '.').astype(float)
df['longitude'] = df['longitude'].astype(str).str.replace(',', '.').astype(float)

# Erstelle eine Liste der Koordinaten
koordinaten = df[['longitude', 'latitude']].values.tolist()

# Funktion zur Erstellung der Anfrage-URL
def erstelle_anfrage_url(start, ziel):
    return f"http://localhost:5000/route/v1/driving/{start[0]},{start[1]};{ziel[0]},{ziel[1]}?overview=false"

# Funktion zur Anfrage an den OSRM-Server
def osrm_anfrage(session, start, ziel):
    url = erstelle_anfrage_url(start, ziel)
    headers = {'Connection': 'keep-alive'}
    try:
        response = session.get(url, headers=headers, timeout=10)  # Timeout auf 10 Sekunden gesetzt
        response.raise_for_status()
        daten = response.json()
        distanz = daten['routes'][0]['distance']
        zeit = daten['routes'][0]['duration']
        return distanz, zeit
    except requests.exceptions.HTTPError as errh:
        logging.error(f"HTTP Fehler: {errh} für URL: {url}")
    except requests.exceptions.ConnectionError as errc:
        logging.error(f"Verbindungsfehler: {errc} für URL: {url}")
    except requests.exceptions.Timeout as errt:
        logging.error(f"Timeout-Fehler: {errt} für URL: {url}")
    except requests.exceptions.RequestException as err:
        logging.error(f"Allgemeiner Fehler: {err} für URL: {url}")
    return None, None

# Initialisiere die Distanz- und Zeitmatrizen
distanzmatrix = pd.DataFrame(index=range(len(koordinaten)), columns=range(len(koordinaten)))
zeitmatrix = pd.DataFrame(index=range(len(koordinaten)), columns=range(len(koordinaten)))

# Begrenze die Anzahl der Threads auf die Hälfte der verfügbaren CPU-Kerne
anzahl_kerne = max(1, os.cpu_count() // 2)

# Konfiguriere die Sitzung mit Retry-Strategie
session = requests.Session()
retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Verwende eine Session und ThreadPoolExecutor für parallele Anfragen
with ThreadPoolExecutor(max_workers=anzahl_kerne) as executor:
    zukunft_zu_index = {
        executor.submit(osrm_anfrage, session, start, ziel): (i, j)
        for i, start in enumerate(koordinaten)
        for j, ziel in enumerate(koordinaten)
        if i != j
    }
    for zukunft in tqdm(as_completed(zukunft_zu_index), total=len(zukunft_zu_index), desc="Anfragen werden bearbeitet"):
        i, j = zukunft_zu_index[zukunft]
        try:
            distanz, zeit = zukunft.result()
            if distanz is not None:
                distanzmatrix.iloc[i, j] = distanz
            else:
                distanzmatrix.iloc[i, j] = -1  # Platzhalter für fehlende Werte
            if zeit is not None:
                zeitmatrix.iloc[i, j] = zeit
            else:
                zeitmatrix.iloc[i, j] = -1  # Platzhalter für fehlende Werte
        except Exception as e:
            logging.error(f"Fehler bei der Verarbeitung von Koordinaten {i}, {j}: {e}")
        time.sleep(0.1)  # Zeitverzögerung beibehalten

# Exportiere die Matrizen in eine Excel-Datei
output_datei = "distanzmatrix_und_zeitmatrix.xlsx"
with pd.ExcelWriter(output_datei, engine='openpyxl') as writer:
    distanzmatrix.to_excel(writer, sheet_name="Distanzmatrix", index=False)
    zeitmatrix.to_excel(writer, sheet_name="Zeitmatrix", index=False)

print(f"Die Distanz- und Zeitmatrizen wurden erfolgreich in die Datei '{output_datei}' exportiert.")
