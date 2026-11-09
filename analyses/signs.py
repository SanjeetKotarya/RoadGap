"""Road sign gap analysis."""

from __future__ import annotations

import pandas as pd
import geopandas as gpd

from analyses import base
from config import default_settings


def _make_fix(place_type):
    mapping = {
        "school": "Add School Ahead and speed limit signs with clear advance warnings.",
        "hospital": "Add a Hospital sign and keep the approach visible from both directions.",
        "crossing": "Add a Pedestrian Crossing sign on both sides of the crossing.",
        "junction": "Add Stop or Give Way signs to guide traffic at the junction.",
        "default": "Add a clear warning sign and follow IRC:67 placement rules.",
    }
    label = place_type.replace("_", " ")
    return (
        f"{mapping.get(place_type, mapping['default'])} "
        f"Place it to serve the {label}. Check the sign size, height and placement against IRC:67."
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
        base.set_analysis_metadata(settings, "signs", 0, None, roads, low_confidence=True)
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

    sign_tags = {"traffic_sign": True, "highway": ["stop", "give_way", "speed_camera"], "traffic_sign:*": True}
    sign_gdf = base.download_features(area_name, sign_tags, settings)
    signs = (
        base.project_to_utm(base.as_point_dataframe(
            gpd.GeoDataFrame(sign_gdf, geometry="geometry", crs="EPSG:4326")
        ))
        if not sign_gdf.empty
        else gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=places.crs)
    )
    eligible = [
        row for _, row in places.iterrows()
        if base.nearest_distance(row.geometry, roads) <= 30
    ]
    if signs.empty:
        base.set_analysis_metadata(settings, "signs", len(eligible), signs, roads, low_confidence=True)
        return pd.DataFrame()

    rows = []
    gap_distance = float(settings.get("sign_distance_m", 50))
    for row in eligible:
        point = row.geometry
        nearest = base.nearest_distance(point, signs)
        if nearest <= gap_distance:
            continue
        nearest_road = base.nearest_highway_road(point, roads)
        if nearest_road is None:
            continue
        place_type = row["place type"]
        speed_kmh, lanes = base.road_speed_lanes(nearest_road, default_speed=40)
        lat, lon = base.point_to_latlon(point, places.crs)
        name = base.display_value(base._first_tag_value(row.get("name")), f"Unnamed {place_type.replace('_', ' ')}")
        road_name = base.display_value(base._first_tag_value(nearest_road.get("name")), "Unnamed road")
        road_note = base.grade_separation_note(nearest_road, roads, point)
        reason = f"No mapped sign was found within {nearest:.0f} m of this place, even though it is on a busy road."
        if road_note:
            reason = f"{reason} {road_note}"
        rows.append({
            "type": "signs",
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

    base.set_analysis_metadata(settings, "signs", len(eligible), signs, roads)
    return pd.DataFrame(rows)
