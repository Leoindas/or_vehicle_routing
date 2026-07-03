"""Schritt ① der Datenpipeline: Adressen -> Geokoordinaten.

Liest die Kunden-Rohliste (Straße/PLZ/Ort) aus einer Excel-Datei, baut daraus
vollständige Adressen und ermittelt über die Google Geocoding API Breiten- und
Längengrad. Ergebnis: `geokodierte_adressen.xlsx` – die Eingabe für Schritt ②
(OSRM-Matrixberechnung, siehe build_matrix_osrm.py).

Voraussetzungen:
  * gültiger Google-Geocoding-API-Schlüssel (unten in API_KEY eintragen)
  * Eingabedatei mit den Spalten T_Straße, T_PLZ, T_ort

Einmaliger Vorlauf – für den Betrieb der App nicht erneut nötig.
"""

import pandas as pd
import requests
import time

# Google Geocoding API-Schlüssel (hier den eigenen Schlüssel eintragen)
API_KEY = 'API_KEY'

# Funktion zur Geokodierung einer einzelnen Adresse
def geocode_address(address):
    url = f'https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={API_KEY}'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            return location['lat'], location['lng']
        else:
            print(f"Fehler bei der Geokodierung von '{address}': {data['status']}")
    else:
        print(f"HTTP-Fehler {response.status_code} bei der Anfrage für '{address}'")
    return None, None

# Adressen aus der Excel-Datei einlesen
df = pd.read_excel('Essen auf Rädern.xls')

# Überprüfen, ob die erforderlichen Spalten vorhanden sind
required_columns = ['T_Straße', 'T_ort', 'T_PLZ']
for col in required_columns:
    if col not in df.columns:
        raise ValueError(f"Spalte '{col}' fehlt in der Excel-Datei.")

# Neue Spalten für die vollständige Adresse und die Koordinaten hinzufügen
df['Adresse'] = df['T_Straße'] + ', ' + df['T_PLZ'].astype(str) + ' ' + df['T_ort'] + ', Deutschland'
df['Latitude'] = None
df['Longitude'] = None

# Geokodierung jeder Adresse
for idx, row in df.iterrows():
    address = row['Adresse']
    lat, lng = geocode_address(address)
    df.at[idx, 'Latitude'] = lat
    df.at[idx, 'Longitude'] = lng
    time.sleep(0.1)  # Kurze Pause, um die API nicht zu überlasten

# Ergebnisse in eine neue Excel-Datei speichern
df.to_excel('geokodierte_adressen.xlsx', index=False)
