"""Pedestrian railing and barrier gap analysis."""

from __future__ import annotations

import pandas as pd
import geopandas as gpd

from analyses import base
from config import default_settings


def _make_fix(place_type):
    label = place_type.replace("_", " ")
    return (
        f"Add pedestrian guard railing near the {label}, use a median railing if needed, "
        "and add a footpath or sidewalk where it is missing."
    )


def analyse(area_name, settings=None):
    settings = settings if settings is not None else default_settings()
    roads = base.highway_roads(base.project_to_utm(base.download_road_graph(area_name, settings)))
    place_tags = {
        "amenity": ["school", "hospital", "clinic", "kindergarten"],
        "highway": ["bus_stop", "crossing"],
    }
    place_gdf = base.download_features(area_name, place_tags, settings)
    if place_gdf.empty:
        base.set_analysis_metadata(settings, "railings", 0, None, roads, low_confidence=True)
        return pd.DataFrame()
    places = base.project_to_utm(base.as_point_dataframe(
        gpd.GeoDataFrame(place_gdf, geometry="geometry", crs="EPSG:4326")
    ))
    places["place type"] = places.apply(
        lambda row: "school" if str(row.get("amenity", "")).lower() in {"school", "kindergarten"}
        else "hospital" if str(row.get("amenity", "")).lower() in {"hospital", "clinic"}
        else "bus_stop" if str(row.get("highway", "")).lower() == "bus_stop"
        else "crossing",
        axis=1,
    )
    places = base.merge_nearby_places(places, distance_m=25)

    barrier_tags = {"barrier": ["guard_rail", "fence", "railing", "kerb"], "highway": ["footway"]}
    barrier_gdf = base.download_features(area_name, barrier_tags, settings)
    barriers = (
        base.project_to_utm(base.as_point_dataframe(
            gpd.GeoDataFrame(barrier_gdf, geometry="geometry", crs="EPSG:4326")
        ))
        if not barrier_gdf.empty
        else gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=places.crs)
    )
    eligible = [
        row for _, row in places.iterrows()
        if base.nearest_distance(row.geometry, roads) <= 30
    ]
    if barriers.empty:
        base.set_analysis_metadata(settings, "railings", len(eligible), barriers, roads, low_confidence=True)
        return pd.DataFrame()

    rows = []
    gap_distance = float(settings.get("railing_distance_m", 40))
    for row in eligible:
        point = row.geometry
        nearest = base.nearest_distance(point, barriers)
        if nearest <= gap_distance:
            continue
        nearest_road = base.nearest_highway_road(point, roads)
        if nearest_road is None:
            continue
        speed_kmh, lanes = base.road_speed_lanes(nearest_road, default_speed=40)
        place_type = row["place type"]
        lat, lon = base.point_to_latlon(point, places.crs)
        name = base.display_value(base._first_tag_value(row.get("name")), f"Unnamed {place_type.replace('_', ' ')}")
        road_name = base.display_value(base._first_tag_value(nearest_road.get("name")), "Unnamed road")
        road_note = base.grade_separation_note(nearest_road, roads, point)
        reason = f"This place is {nearest:.0f} m from a mapped barrier or sidewalk and may need a guard rail or footpath."
        if road_note:
            reason = f"{reason} {road_note}"
        rows.append({
            "type": "railings",
            "rank": 0,
            "place name": name,
            "place type": place_type,
            "merged from N mapped points": int(row.get("merged from N mapped points", 1)),
            "lat": lat,
            "lon": lon,
            "road name": road_name,
            "lanes": lanes,
            "speed": int(speed_kmh),
            "speed status": "mapped" if base._first_tag_value(nearest_road.get("maxspeed")) is not None else "assumed",
            "distance to nearest": round(nearest, 1),
            **base.score_component_values(nearest, speed_kmh, lanes, place_type),
            "score": 0.0,
            "confidence": "normal",
            "suggested fix": _make_fix(place_type),
            "reason": reason,
            "road note": road_note,
            "street view link": base.street_view_link(lat, lon),
            "is_gap": True,
        })

    base.set_analysis_metadata(settings, "railings", len(eligible), barriers, roads)
    return pd.DataFrame(rows)
