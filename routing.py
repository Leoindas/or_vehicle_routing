"""Kernlogik der Tourenoptimierung.

Liest die vorberechneten Distanz-/Zeitmatrizen aus einer Excel-Datei und löst
das Vehicle-Routing-Problem (VRP) mit Google OR-Tools. Die Funktionen sind
bewusst frei von jeglichem UI-Code, damit sie sich testen und wiederverwenden
lassen (Streamlit-App, CLI, Notebook ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2


# --------------------------------------------------------------------------- #
# Datenmodelle
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Stop:
    """Ein Knoten im Netz (Depot oder Kunde)."""

    node: int
    address: str
    lat: float
    lon: float


@dataclass
class Route:
    """Eine Fahrzeugroute inkl. Depot am Anfang und Ende."""

    vehicle: int
    stops: list[Stop]
    duration_min: float
    distance_km: float

    @property
    def num_addresses(self) -> int:
        # Depot am Anfang und Ende zählen nicht als Kundenadresse.
        return max(len(self.stops) - 2, 0)


@dataclass
class Solution:
    routes: list[Route] = field(default_factory=list)
    total_duration_min: float = 0.0
    total_distance_km: float = 0.0

    @property
    def num_vehicles_used(self) -> int:
        return len(self.routes)

    @property
    def num_addresses(self) -> int:
        return sum(r.num_addresses for r in self.routes)


# --------------------------------------------------------------------------- #
# Excel einlesen
# --------------------------------------------------------------------------- #
def load_matrix(path, sheet: str) -> list[list[float]]:
    """Liest eine n×n-Matrix (Zeit in Sekunden oder Distanz in Metern)."""
    df = pd.read_excel(path, sheet_name=sheet, index_col=0)
    # Werte können als Text mit Komma-Dezimaltrennung vorliegen -> robust casten.
    df = df.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return df.astype(float).values.tolist()


def load_locations(path, sheet: str = "Matching") -> list[Stop]:
    """Liest die Adressen und Koordinaten (Reihenfolge = Matrix-Reihenfolge)."""
    df = pd.read_excel(path, sheet_name=sheet)
    return [
        Stop(node=i, address=str(row["Adresse"]),
             lat=float(row["latitude"]), lon=float(row["longitude"]))
        for i, row in df.reset_index(drop=True).iterrows()
    ]


# --------------------------------------------------------------------------- #
# Solver
# --------------------------------------------------------------------------- #
def solve(
    *,
    objective: str,
    locations: list[Stop],
    time_matrix: list[list[float]],
    distance_matrix: list[list[float]],
    num_vehicles: int,
    max_stops: int,
    max_route_limit: int,
    service_time_s: int = 0,
    time_limit_s: int = 30,
    depot: int = 0,
) -> Solution | None:
    """Löst das VRP und gibt eine strukturierte Lösung zurück (oder ``None``).

    Parameters
    ----------
    objective:
        ``"time"`` optimiert die Gesamtfahrzeit, ``"distance"`` die Gesamtstrecke.
    max_route_limit:
        Obergrenze pro Route – bei ``"time"`` in Sekunden, bei ``"distance"``
        in Metern (passend zur gewählten Kostenmatrix).
    service_time_s:
        Zusätzliche Servicezeit pro Stopp (nur bei Zeitoptimierung relevant).
    """
    cost_matrix = time_matrix if objective == "time" else distance_matrix
    add_per_stop = service_time_s if objective == "time" else 0

    n = len(cost_matrix)
    manager = pywrapcp.RoutingIndexManager(n, num_vehicles, depot)
    routing = pywrapcp.RoutingModel(manager)

    # Kosten-Callback (die zu minimierende Größe).
    def cost_callback(from_index, to_index):
        f = manager.IndexToNode(from_index)
        t = manager.IndexToNode(to_index)
        cost = int(cost_matrix[f][t])
        if not routing.IsEnd(to_index):
            cost += add_per_stop
        return cost

    transit_index = routing.RegisterTransitCallback(cost_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

    # Obergrenze für Fahrzeit bzw. -strecke pro Route.
    routing.AddDimension(transit_index, 0, max_route_limit, True, "RouteCost")

    # Stopp-Begrenzung: Jeder Kunde zählt 1, das Depot 0. Die Fahrzeug-
    # Kapazität erzwingt höchstens ``max_stops`` Adressen pro Route.
    def stop_callback(from_index):
        return 0 if manager.IndexToNode(from_index) == depot else 1

    stop_index = routing.RegisterUnaryTransitCallback(stop_callback)
    routing.AddDimensionWithVehicleCapacity(
        stop_index, 0, [max_stops] * num_vehicles, True, "StopCount"
    )

    # Suchstrategie: Savings als Startlösung, danach Guided Local Search.
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.SAVINGS
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.seconds = time_limit_s

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return None

    return _extract_solution(
        manager, routing, solution, locations,
        time_matrix, distance_matrix, add_per_stop,
    )


def _extract_solution(
    manager, routing, solution, locations,
    time_matrix, distance_matrix, add_per_stop,
) -> Solution:
    """Übersetzt die OR-Tools-Lösung in ``Route``/``Solution``-Objekte.

    Fahrzeit und Strecke werden immer aus beiden Rohmatrizen berechnet, sodass
    beide Kennzahlen unabhängig vom gewählten Optimierungsziel vorliegen.
    """
    result = Solution()
    vehicle_counter = 1

    for vehicle_id in range(routing.vehicles()):
        index = routing.Start(vehicle_id)
        nodes: list[int] = []
        while not routing.IsEnd(index):
            nodes.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        nodes.append(manager.IndexToNode(index))  # Depot am Ende

        if len(nodes) <= 2:
            continue  # Fahrzeug wurde nicht eingesetzt

        seconds = 0.0
        meters = 0.0
        for a, b in zip(nodes, nodes[1:]):
            seconds += time_matrix[a][b]
            meters += distance_matrix[a][b]

        num_stops = len(nodes) - 2
        seconds += add_per_stop * num_stops

        route = Route(
            vehicle=vehicle_counter,
            stops=[locations[i] for i in nodes],
            duration_min=seconds / 60,
            distance_km=meters / 1000,
        )
        result.routes.append(route)
        result.total_duration_min += route.duration_min
        result.total_distance_km += route.distance_km
        vehicle_counter += 1

    return result
