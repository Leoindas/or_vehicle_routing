"""Kartendarstellung und externe Links für berechnete Routen.

Die Streckenführung ("wie fährt das Auto entlang der Straßen") wird optional
über einen OSRM-Server geholt. Ohne erreichbaren Server fällt die Karte auf
Luftlinien zwischen den Stopps zurück – die App bleibt so ohne eigene
Infrastruktur lauffähig.
"""

from __future__ import annotations

import folium
import requests

from routing import Route, Stop

# Öffentlicher OSRM-Demoserver (Rate-Limited). Für den Eigenbetrieb einfach die
# lokale URL (z. B. "http://localhost:5000") übergeben.
PUBLIC_OSRM_URL = "https://router.project-osrm.org"

ROUTE_COLORS = [
    "red", "blue", "green", "orange", "purple", "darkred", "darkblue",
    "darkgreen", "cadetblue", "pink", "black", "gray", "beige", "lightgreen",
]


def _osrm_geometry(stops: list[Stop], base_url: str, timeout: int = 20):
    """Holt die Straßen-Geometrie einer Route von OSRM. ``None`` bei Fehler."""
    coords = ";".join(f"{s.lon},{s.lat}" for s in stops)
    url = f"{base_url}/route/v1/driving/{coords}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if data.get("routes"):
            geometry = data["routes"][0]["geometry"]["coordinates"]
            return [(lat, lon) for lon, lat in geometry]  # GeoJSON: [lon, lat]
    except requests.RequestException:
        return None
    return None


def build_map(routes: list[Route], osrm_url: str | None = None) -> folium.Map:
    """Erzeugt eine Folium-Karte mit allen Routen, Markern und Legende."""
    depot = routes[0].stops[0]
    fmap = folium.Map(location=[depot.lat, depot.lon], zoom_start=11,
                      tiles="cartodbpositron")

    for i, route in enumerate(routes):
        color = ROUTE_COLORS[i % len(ROUTE_COLORS)]

        line = _osrm_geometry(route.stops, osrm_url) if osrm_url else None
        if line is None:  # Fallback: Luftlinie
            line = [(s.lat, s.lon) for s in route.stops]

        folium.PolyLine(
            line, color=color, weight=4, opacity=0.8,
            tooltip=f"Route {route.vehicle} · {route.num_addresses} Adressen",
        ).add_to(fmap)

        # Kundenmarker (Depot am Ende überspringen – identisch mit Start).
        for j, stop in enumerate(route.stops[:-1]):
            if j == 0:
                folium.Marker(
                    [stop.lat, stop.lon], popup=f"Depot: {stop.address}",
                    icon=folium.Icon(color="black", icon="home", prefix="fa"),
                ).add_to(fmap)
            else:
                folium.CircleMarker(
                    [stop.lat, stop.lon], radius=5, color=color, fill=True,
                    fill_color=color, fill_opacity=0.9,
                    popup=f"Route {route.vehicle}: {stop.address}",
                ).add_to(fmap)

    _add_legend(fmap, routes)
    return fmap


def _add_legend(fmap: folium.Map, routes: list[Route]) -> None:
    rows = "".join(
        f'<div style="margin:3px 0;display:flex;align-items:center;color:#222;">'
        f'<span style="background:{ROUTE_COLORS[i % len(ROUTE_COLORS)]};'
        f'width:14px;height:14px;display:inline-block;margin-right:8px;'
        f'border-radius:3px;border:1px solid rgba(0,0,0,.25);"></span>'
        f'Route {r.vehicle} · {r.num_addresses} Adr.</div>'
        for i, r in enumerate(routes)
    )
    html = (
        '<div style="position:fixed;bottom:24px;left:24px;z-index:9999;'
        'background:#ffffff;padding:10px 14px;border:1px solid #999;'
        'border-radius:6px;font-size:13px;line-height:1.3;'
        'color:#222;font-family:Arial,Helvetica,sans-serif;'
        'box-shadow:0 1px 6px rgba(0,0,0,.35);">'
        '<div style="font-weight:700;color:#111;margin-bottom:4px;">Routen</div>'
        + rows + "</div>"
    )
    fmap.get_root().html.add_child(folium.Element(html))


def google_maps_links(route: Route, max_points: int = 10) -> list[str]:
    """Erzeugt Google-Maps-Links (max. 10 Punkte je Link -> ggf. mehrere)."""
    stops = route.stops
    links: list[str] = []
    i = 0
    while i < len(stops) - 1:
        segment = stops[i:i + max_points]
        if len(segment) >= 2:
            origin = f"{segment[0].lat},{segment[0].lon}"
            dest = f"{segment[-1].lat},{segment[-1].lon}"
            waypoints = "|".join(f"{s.lat},{s.lon}" for s in segment[1:-1])
            url = (
                "https://www.google.com/maps/dir/?api=1"
                f"&origin={origin}&destination={dest}&travelmode=driving"
            )
            if waypoints:
                url += f"&waypoints={waypoints}"
            links.append(url)
        # Segmente überlappen um einen Punkt, damit die Kette lückenlos bleibt.
        i += max_points - 1
    return links
