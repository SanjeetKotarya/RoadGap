"""Crossing gap analysis."""

from __future__ import annotations

import math

import pandas as pd
import geopandas as gpd

from analyses import base
from config import default_settings


def _make_fix(place_type, road_name, speed_kmh, lanes):
    place_label = place_type.replace("_", " ")
    if speed_kmh >= 50 or lanes >= 4:
        base_fix = f"Pedestrian refuge island with signalised crossing for this {place_label}; consider a foot overbridge only if traffic is very heavy."
    else:
        base_fix = f"Zebra crossing for this {place_label} with warning signs and a raised crossing or speed breaker before it."

    if place_type in {"school", "kindergarten"}:
        base_fix += " Add School Zone signs, 25-30 km/h speed limit signs, rumble strips, and guard rails guiding children to the crossing."
    elif place_type == "bus_stop":
        base_fix += " Move or add a crossing within 10-30 m of the bus stop and add railings so people use the crossing."
    elif place_type == "station":
        base_fix += " Provide a safe crossing near the station entrance and guide pedestrians to it with railings."
    elif place_type == "hospital":
        base_fix += " Add a clearly marked crossing with good lighting."

    base_fix += " Always add good street lighting and a pedestrian crossing sign on both sides. Check IRC:103, IRC:67 and IRC:35 before final design."
    return base_fix


def _tag_text(value, fallback):
    value = base._first_tag_value(value)
    return str(value) if value is not None else fallback


def _place_type(row):
    amenity = _tag_text(row.get("amenity"), "").lower()
    highway = _tag_text(row.get("highway"), "").lower()
    railway = _tag_text(row.get("railway"), "").lower()
    if amenity in {"school", "college", "kindergarten"}:
        return amenity
    if amenity in {"hospital", "clinic"}:
        return "hospital"
    if amenity == "marketplace" or _tag_text(row.get("shop"), ""):
        return "market"
    if railway in {"station", "halt"}:
        return "station"
    if highway == "bus_stop" or _tag_text(row.get("public_transport"), "").lower() == "platform":
        return "bus_stop"
    if amenity == "place_of_worship":
        return "place_of_worship"
    return "important place"


def analyse(area_name, settings=None):
    settings = settings if settings is not None else default_settings()
    area_query, _, warning = base.area_to_query(area_name, settings)
    roads = base.download_road_graph(area_name, settings)
    roads = base.project_to_utm(roads)

    roads = base.highway_roads(roads)

    place_tags = {
        "highway": ["bus_stop"],
        "public_transport": "platform",
        "amenity": ["school", "college", "kindergarten", "hospital", "clinic", "marketplace", "place_of_worship"],
        "shop": True,
        "railway": ["station", "halt"],
    }
    place_gdf = base.download_features(area_name, place_tags, settings)
    if place_gdf.empty:
        base.set_analysis_metadata(settings, "crossings", 0, None, roads, low_confidence=True)
        return pd.DataFrame(columns=["type", "rank", "place name", "place type", "lat", "lon", "road name", "lanes", "speed", "distance to nearest", "score", "suggested fix", "reason", "street view link"])

    places = gpd.GeoDataFrame(place_gdf, geometry="geometry", crs="EPSG:4326")
    places = base.as_point_dataframe(places)
    places = base.project_to_utm(places)
    places["place type"] = places.apply(_place_type, axis=1)
    places = base.merge_nearby_places(places, distance_m=25)

    gaps = []
    crossing_tags = {"highway": ["crossing"], "footway": ["crossing"], "crossing": True}
    crossing_gdf = base.download_features(area_name, crossing_tags, settings)
    if not crossing_gdf.empty:
        crossings = gpd.GeoDataFrame(crossing_gdf, geometry="geometry", crs="EPSG:4326")
        crossings = base.as_point_dataframe(crossings)
        crossings = base.project_to_utm(crossings)
        crossings = crossings.drop_duplicates(subset=["geometry"]).copy()
    else:
        crossings = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    if not crossings.empty and "railway" in crossings.columns:
        crossings = crossings.loc[crossings["railway"].isna()].copy()

    eligible_count = sum(base.nearest_distance(row.geometry, roads) <= 30 for _, row in places.iterrows())
    if crossings.empty:
        settings["places_checked"] = eligible_count
        base.set_analysis_metadata(settings, "crossings", eligible_count, crossings, roads, low_confidence=True)
        return pd.DataFrame(columns=[
            "type", "rank", "place name", "place type", "lat", "lon", "road name",
            "lanes", "speed", "speed status", "distance to nearest", "score",
            "suggested fix", "reason", "street view link", "is_gap", "confidence",
            "score_distance_component", "score_speed_component", "score_lanes_component",
            "score_place_component",
        ])

    checked = []
    for _, row in places.iterrows():
        point = row.geometry
        distance_to_road = base.nearest_distance(point, roads)
        if distance_to_road > 30:
            continue

        lat, lon = base.point_to_latlon(point, places.crs)
        place_type = row["place type"]
        place_name = _tag_text(row.get("name"), f"Unnamed {place_type.replace('_', ' ')}")
        nearest_road = base.nearest_highway_road(point, roads)
        road_name = _tag_text(nearest_road.get("name") if nearest_road is not None else None, "Unnamed road")
        checked.append({
            "place name": place_name,
            "place type": place_type,
            "lat": lat,
            "lon": lon,
            "road name": road_name,
            "is_gap": False,
            "score": 0,
            "geometry": point,
        })

        nearest_crossing = base.nearest_distance(point, crossings)
        gap_distance = float(settings.get("gap_distance_m", 100))
        if nearest_crossing <= gap_distance:
            continue
        checked[-1]["is_gap"] = True

        speed_kmh, lanes = base.road_speed_lanes(nearest_road, default_speed=30) if nearest_road is not None else (30, 2)
        speed_status = "mapped" if nearest_road is not None and _tag_text(nearest_road.get("maxspeed"), "") else "assumed"
        road_note = base.grade_separation_note(nearest_road, roads, point)
        score_type = place_type if place_type in {"school", "kindergarten", "hospital", "bus_stop", "station", "market"} else "default"
        score = base.place_score(nearest_crossing, speed_kmh, lanes, score_type, gap_distance)
        if math.isfinite(nearest_crossing):
            crossing_distance = round(nearest_crossing, 1)
            reason = (
                f"This area is a {place_type.replace('_', ' ')} near {road_name}, "
                f"and the nearest mapped crossing is {nearest_crossing:.0f} m away."
            )
        else:
            crossing_distance = None
            reason = (
                f"This area is a {place_type.replace('_', ' ')} near {road_name}; "
                "no mapped pedestrian crossing was found in the extract."
            )
        if road_note:
            reason = f"{reason} {road_note}"
        fix = _make_fix(place_type, road_name, speed_kmh, lanes)

        gaps.append({
            "type": "crossings",
            "rank": 0,
            "place name": place_name,
            "place type": place_type,
            "merged from N mapped points": int(row.get("merged from N mapped points", 1)),
            "lat": lat,
            "lon": lon,
            "road name": road_name,
            "lanes": lanes,
            "speed": int(speed_kmh),
            "speed status": speed_status,
            "distance to nearest": crossing_distance,
            **base.score_component_values(nearest_crossing, speed_kmh, lanes, score_type),
            "score": round(score, 1),
            "suggested fix": fix,
            "reason": reason,
            "road note": road_note,
            "street view link": base.street_view_link(lat, lon),
            "is_gap": True,
            "confidence": "normal",
        })

    settings["places_checked"] = len(checked)
    base.set_analysis_metadata(settings, "crossings", len(checked), crossings, roads)

    if not gaps:
        return pd.DataFrame(columns=[
            "type", "rank", "place name", "place type", "lat", "lon", "road name",
            "lanes", "speed", "speed status", "distance to nearest", "score",
            "suggested fix", "reason", "street view link", "is_gap", "confidence",
            "score_distance_component", "score_speed_component", "score_lanes_component",
            "score_place_component",
        ])

    df = pd.DataFrame(gaps)
    df = df.sort_values(by="score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    df["distance to nearest"] = pd.to_numeric(df["distance to nearest"], errors="coerce").round(1)
    df["score"] = df["score"].round(1)
    return df
