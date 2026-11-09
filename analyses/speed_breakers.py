"""Speed breaker / traffic calming gap analysis."""

from __future__ import annotations

import pandas as pd
import geopandas as gpd

from analyses import base
from config import default_settings


def _make_fix(place_type):
    label = place_type.replace("_", " ")
    fix = f"Add a speed hump or raised crossing before this {label}, plus advance warning signs and paint markings."
    if place_type in {"school", "kindergarten"}:
        fix += " Use a school zone speed limit and keep the calming feature away from emergency routes."
    fix += " Check IRC:99 before placing speed breakers on heavy-traffic roads."
    return fix


def analyse(area_name, settings=None):
    settings = settings if settings is not None else default_settings()
    roads = base.highway_roads(base.project_to_utm(base.download_road_graph(area_name, settings)))
    important_tags = {
        "amenity": ["school", "kindergarten", "hospital", "clinic", "marketplace"],
        "highway": ["bus_stop", "crossing"],
    }
    place_gdf = base.download_features(area_name, important_tags, settings)
    if place_gdf.empty:
        base.set_analysis_metadata(settings, "speed_breakers", 0, None, roads, low_confidence=True)
        return pd.DataFrame()
    places = base.project_to_utm(base.as_point_dataframe(
        gpd.GeoDataFrame(place_gdf, geometry="geometry", crs="EPSG:4326")
    ))
    places["place type"] = places.apply(
        lambda row: "school" if str(row.get("amenity", "")).lower() in {"school", "kindergarten"}
        else "hospital" if str(row.get("amenity", "")).lower() in {"hospital", "clinic"}
        else "bus_stop" if str(row.get("highway", "")).lower() == "bus_stop"
        else "crossing" if str(row.get("highway", "")).lower() == "crossing"
        else "market",
        axis=1,
    )
    places = base.merge_nearby_places(places, distance_m=25)

    calming_tags = {"traffic_calming": ["bump", "hump", "table", "cushion", "rumble_strip", "chicane", "island"]}
    calming_gdf = base.download_features(area_name, calming_tags, settings)
    calming = (
        base.project_to_utm(base.as_point_dataframe(
            gpd.GeoDataFrame(calming_gdf, geometry="geometry", crs="EPSG:4326")
        ))
        if not calming_gdf.empty
        else gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=places.crs)
    )
    eligible = [
        row for _, row in places.iterrows()
        if base.nearest_distance(row.geometry, roads) <= 30
    ]
    if calming.empty:
        base.set_analysis_metadata(settings, "speed_breakers", len(eligible), calming, roads, low_confidence=True)
        return pd.DataFrame()

    rows = []
    gap_distance = float(settings.get("calming_distance_m", 60))
    for row in eligible:
        point = row.geometry
        nearest = base.nearest_distance(point, calming)
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
        reason = f"The place is {nearest:.0f} m from a mapped calming feature and is on a road with {speed_kmh} km/h traffic."
        if road_note:
            reason = f"{reason} {road_note}"
        rows.append({
            "type": "speed_breakers",
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

    base.set_analysis_metadata(settings, "speed_breakers", len(eligible), calming, roads)
    return pd.DataFrame(rows)
