"""Streamlit-Web-App zur Tourenoptimierung für einen Essen-auf-Rädern-Dienst.

Start:  streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import mapping
import routing

DATA_DIR = Path(__file__).parent / "data"

st.set_page_config(
    page_title="Essen auf Rädern – Tourenoptimierung",
    page_icon="🍲",
    layout="wide",
)


# --------------------------------------------------------------------------- #
# Daten laden (gecacht)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def load_dataset(source) -> tuple[list, list, list]:
    """Lädt Adressen sowie Zeit-/Distanzmatrix aus einer Excel-Datei."""
    locations = routing.load_locations(source, "Matching")
    time_matrix = routing.load_matrix(source, "Zeitmatrix")
    distance_matrix = routing.load_matrix(source, "Distanzmatrix")
    return locations, time_matrix, distance_matrix


# --------------------------------------------------------------------------- #
# Kopf
# --------------------------------------------------------------------------- #
st.title("🍲 Essen auf Rädern – Tourenoptimierung")
st.caption(
    "Vehicle-Routing mit Google OR-Tools (Savings + Guided Local Search). "
    "Ordnet Lieferadressen effizient auf Fahrzeuge auf und visualisiert die "
    "Touren auf einer Karte."
)

with st.expander("ℹ️  Über dieses Projekt & Herkunft der Daten"):
    st.markdown(
        """
**Ausgangslage:** Gegeben war eine **Liste von Kundenadressen** (Straße, PLZ,
Ort) eines Essen-auf-Rädern-Dienstes. Bis zu den fertig optimierten Touren
waren mehrere Schritte nötig:

1. **Geokodierung** – jede Adresse wird über die **Google Geocoding API** in
   Koordinaten (Breiten-/Längengrad) umgewandelt.
2. **Reisedaten via OSRM** – ein selbst unter **Linux** aufgesetzter
   **OSRM-Routing-Server** (auf Basis der OpenStreetMap-Deutschlandkarte)
   liefert für **jedes Adresspaar** die reale **Strecke (in Metern)** und die
   **Fahrzeit (in Sekunden)**.
3. **Distanz- & Zeitmatrix** – aus diesen Paar-Abfragen entstehen die beiden
   n×n-Matrizen, die hier als Eingabe dienen (vorberechnet in den
   Beispieldatensätzen).
4. **Optimierung** – diese App löst damit das **Vehicle-Routing-Problem** mit
   Google **OR-Tools** (Savings-Heuristik + Guided Local Search) und
   visualisiert die Touren auf der Karte.

Code & ausführliche Dokumentation:
[github.com/Leoindas/or_vehicle_routing](https://github.com/Leoindas/or_vehicle_routing)
        """
    )

# --------------------------------------------------------------------------- #
# Sidebar: Datenquelle & Parameter
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("1 · Daten")
    examples = sorted(DATA_DIR.glob("*.xlsx"))
    example_names = [p.name for p in examples]
    choice = st.selectbox(
        "Datensatz",
        example_names + ["Eigene Datei hochladen …"],
        help="Excel mit den Blättern 'Matching', 'Zeitmatrix', 'Distanzmatrix'.",
    )
    if choice == "Eigene Datei hochladen …":
        uploaded = st.file_uploader("Excel-Datei (.xlsx)", type="xlsx")
        source = uploaded
    else:
        source = DATA_DIR / choice

    st.header("2 · Parameter")
    objective_label = st.radio(
        "Optimierungsziel",
        ["Zeit (Fahrminuten)", "Distanz (km)"],
        help="Was soll minimiert werden – die Gesamtfahrzeit oder die Strecke?",
    )
    objective = "time" if objective_label.startswith("Zeit") else "distance"

    num_vehicles = st.slider("Anzahl Fahrzeuge", 1, 30, 15)
    max_stops = st.slider("Max. Adressen pro Route", 1, 60, 40)

    if objective == "time":
        max_limit_ui = st.slider("Max. Fahrzeit pro Route (Min)", 10, 300, 120)
        max_route_limit = max_limit_ui * 60
        service_time = st.slider("Servicezeit pro Stopp (Sek)", 0, 600, 0)
    else:
        max_limit_ui = st.slider("Max. Strecke pro Route (km)", 5, 300, 120)
        max_route_limit = max_limit_ui * 1000
        service_time = 0

    with st.expander("Erweitert"):
        time_limit = st.slider("Rechenzeit-Limit (Sek)", 5, 120, 30)
        use_osrm = st.checkbox(
            "Straßenverlauf via OSRM (öffentl. Demoserver)",
            value=False,
            help="Ohne Haken werden Luftlinien gezeichnet – schneller und ohne "
            "Rate-Limits. Mit Haken echte Straßenführung über router."
            "project-osrm.org.",
        )

    run = st.button("🚚 Touren optimieren", type="primary", use_container_width=True)


# --------------------------------------------------------------------------- #
# Ausführung
# --------------------------------------------------------------------------- #
if source is None:
    st.info("Bitte links eine Excel-Datei hochladen oder einen Beispieldatensatz wählen.")
    st.stop()

try:
    locations, time_matrix, distance_matrix = load_dataset(source)
except Exception as exc:  # noqa: BLE001 – Nutzer soll die Ursache sehen
    st.error(f"Datei konnte nicht gelesen werden: {exc}")
    st.stop()

st.success(f"Datensatz geladen: **{len(locations)} Adressen** (inkl. Depot).")

if not run:
    st.stop()

with st.spinner("Optimiere Touren …"):
    solution = routing.solve(
        objective=objective,
        locations=locations,
        time_matrix=time_matrix,
        distance_matrix=distance_matrix,
        num_vehicles=num_vehicles,
        max_stops=max_stops,
        max_route_limit=max_route_limit,
        service_time_s=service_time,
        time_limit_s=time_limit,
    )

if solution is None or not solution.routes:
    st.error(
        "Keine zulässige Lösung gefunden. Tipp: mehr Fahrzeuge, höhere "
        "Adressen-Grenze oder höheres Zeit-/Streckenlimit erlauben."
    )
    st.stop()

# --------------------------------------------------------------------------- #
# Kennzahlen
# --------------------------------------------------------------------------- #
c1, c2, c3, c4 = st.columns(4)
c1.metric("Fahrzeuge im Einsatz", solution.num_vehicles_used)
c2.metric("Bediente Adressen", solution.num_addresses)
c3.metric("Gesamtfahrzeit", f"{solution.total_duration_min:,.0f} min")
c4.metric("Gesamtstrecke", f"{solution.total_distance_km:,.1f} km")

# --------------------------------------------------------------------------- #
# Karte + Details
# --------------------------------------------------------------------------- #
map_col, detail_col = st.columns([3, 2])

with map_col:
    st.subheader("Karte")
    osrm_url = mapping.PUBLIC_OSRM_URL if use_osrm else None
    with st.spinner("Zeichne Karte …"):
        fmap = mapping.build_map(solution.routes, osrm_url=osrm_url)
    st_folium(fmap, use_container_width=True, height=560, returned_objects=[])

with detail_col:
    st.subheader("Routen")
    table = pd.DataFrame(
        {
            "Route": r.vehicle,
            "Adressen": r.num_addresses,
            "Fahrzeit (min)": round(r.duration_min, 1),
            "Strecke (km)": round(r.distance_km, 1),
        }
        for r in solution.routes
    )
    st.dataframe(table, hide_index=True, use_container_width=True)

    st.download_button(
        "⬇️ Routen als CSV",
        table.to_csv(index=False).encode("utf-8"),
        file_name="routen.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.subheader("Google-Maps-Navigation")
    for route in solution.routes:
        links = mapping.google_maps_links(route)
        parts = " · ".join(
            f"[Teil {k + 1}]({url})" for k, url in enumerate(links)
        )
        st.markdown(f"**Route {route.vehicle}:** {parts}")

# --------------------------------------------------------------------------- #
# Stopp-Liste je Route
# --------------------------------------------------------------------------- #
st.subheader("Stopps im Detail")
for route in solution.routes:
    with st.expander(
        f"Route {route.vehicle} – {route.num_addresses} Adressen · "
        f"{route.duration_min:.0f} min · {route.distance_km:.1f} km"
    ):
        stops_df = pd.DataFrame(
            {"Reihenfolge": i, "Adresse": s.address}
            for i, s in enumerate(route.stops)
        )
        st.dataframe(stops_df, hide_index=True, use_container_width=True)
