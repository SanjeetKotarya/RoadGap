"""Shared helpers used by all analysis modules."""

from __future__ import annotations

import hashlib
import io
import json
import math
import pickle
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import osmnx as ox
import pandas as pd
from shapely.geometry import Point, shape

from config import OVERPASS_ENDPOINTS, default_settings

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
OUTPUT_DIR = ROOT / "output"
DOWNLOAD_ERRORS = []

# Nominatim geocoding and Overpass feature queries are separate services.
# A small timeout lets the downloader move on to another public Overpass instance.
ox.settings.requests_timeout = 15
ACTIVE_OVERPASS_URL = OVERPASS_ENDPOINTS[0]
FAILED_OVERPASS_UNTIL = {}
FAILED_OVERPASS_REASON = {}
LOCAL_EXTRACT_CACHE = {}
LOCAL_UPLOAD_DIR = tempfile.TemporaryDirectory(prefix="road-safety-extract-")
LOCAL_UPLOAD_PATHS = {}


def ensure_dirs():
    CACHE_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    return OUTPUT_DIR


def ensure_output_dir():
    return ensure_dirs()


def create_run_output_dir(area_name: str, analyses):
    ensure_dirs()
    area_slug = re.sub(r"[^a-z0-9]+", "-", str(area_name).lower()).strip("-")[:48] or "analysis"
    analysis_slug = "-".join(
        re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
        for name in analyses
    ) or "analysis"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = OUTPUT_DIR / f"{timestamp}-{area_slug}-{analysis_slug}-{uuid4().hex[:6]}"
    run_dir.mkdir()
    return run_dir


def make_cache_key(prefix: str, area_name: str, tags: dict | None = None):
    text = f"{prefix}:{area_name.strip().lower()}"
    if tags:
        text += ":" + json.dumps(tags, sort_keys=True)
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def load_pickle(path: Path):
    if path.exists():
        try:
            with path.open("rb") as handle:
                return pickle.load(handle)
        except Exception:
            return None
    return None


def save_pickle(path: Path, obj):
    with path.open("wb") as handle:
        pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)


def safe_geo_dataframe(gdf: gpd.GeoDataFrame | None):
    if gdf is None or getattr(gdf, "empty", True):
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
    gdf = gdf.copy()
    if gdf.crs is None:
        gdf.set_crs(4326, inplace=True)
    return gdf


def as_point_dataframe(gdf: gpd.GeoDataFrame | None):
    gdf = safe_geo_dataframe(gdf)
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
    out = gdf.copy()
    if gdf.crs is not None and gdf.crs.is_geographic:
        projected = ox.projection.project_gdf(gdf)
        out["geometry"] = projected.geometry.centroid.to_crs(gdf.crs)
    else:
        out["geometry"] = out.geometry.centroid
    valid_geometry = out.geometry.notna() & ~out.geometry.is_empty
    valid_coordinates = out.geometry.apply(
        lambda point: (
            point is not None
            and math.isfinite(point.x)
            and math.isfinite(point.y)
        )
    )
    return out.loc[valid_geometry & valid_coordinates].copy()


def merge_nearby_places(gdf: gpd.GeoDataFrame, distance_m: float = 25):
    if gdf is None or gdf.empty:
        return safe_geo_dataframe(gdf)
    if "place type" not in gdf.columns:
        raise ValueError("Places must have a 'place type' column before they can be merged")
    frame = gdf.copy()
    parent = list(range(len(frame)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first, second):
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    grouped_indices = {}
    for index, place_type in enumerate(frame["place type"].astype(str)):
        grouped_indices.setdefault(place_type, []).append(index)
    for indices in grouped_indices.values():
        for offset, first in enumerate(indices):
            first_geometry = frame.geometry.iloc[first]
            for second in indices[offset + 1:]:
                if first_geometry.distance(frame.geometry.iloc[second]) <= distance_m:
                    union(first, second)

    clusters = {}
    for index in range(len(frame)):
        clusters.setdefault(find(index), []).append(index)
    merged_rows = []
    for indices in clusters.values():
        group = frame.iloc[indices]
        row = group.iloc[0].copy()
        row.geometry = Point(
            sum(point.x for point in group.geometry) / len(group),
            sum(point.y for point in group.geometry) / len(group),
        )
        previous_count = pd.to_numeric(
            group.get("merged from N mapped points", pd.Series(1, index=group.index)),
            errors="coerce",
        ).fillna(1)
        row["merged from N mapped points"] = int(previous_count.sum())
        if "name" in group.columns:
            names = [
                _first_tag_value(value)
                for value in group["name"]
            ]
            row["name"] = next((name for name in names if name is not None), None)
        merged_rows.append(row)
    return gpd.GeoDataFrame(merged_rows, geometry="geometry", crs=frame.crs).reset_index(drop=True)


def area_to_query(area_name: str, settings=None):
    settings = default_settings(settings or {})
    area_name = (area_name or "").strip()
    if not area_name:
        raise ValueError("Please enter a place name or location.")

    if settings.get("offline_mode"):
        coord_match = re.match(r"^\s*([-+]?\d*\.?\d+)\s*[, ]\s*([-+]?\d*\.?\d+)\s*(?:[, ]\s*(\d+(?:\.\d+)?)\s*)?$", area_name)
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            radius = float(coord_match.group(3) or settings.get("fallback_radius_m", 1500))
            return (lat, lon, radius), area_name, "Using coordinates to select data from the local extract."
        return area_name, area_name, "Using the uploaded local extract; its features should cover the selected study area."

    area_limit = float(settings.get("area_size_limit_m", 3000))
    fallback_lat = settings.get("fallback_lat")
    fallback_lon = settings.get("fallback_lon")
    fallback_radius = settings.get("fallback_radius_m", area_limit)

    coord_match = re.match(r"^\s*([-+]?\d*\.?\d+)\s*[, ]\s*([-+]?\d*\.?\d+)\s*(?:[, ]\s*(\d+(?:\.\d+)?)\s*)?$", area_name)
    if coord_match:
        lat = float(coord_match.group(1))
        lon = float(coord_match.group(2))
        radius = float(coord_match.group(3) or fallback_radius or 1500)
        return (lat, lon, radius), area_name, "Using coordinates for the analysis."

    try:
        coords = ox.geocode(area_name)
        if isinstance(coords, tuple) and len(coords) == 2:
            lat, lon = float(coords[0]), float(coords[1])
            radius = min(max(float(settings.get("fallback_radius_m", 1500)), 800), 3000)
            return (lat, lon, radius), area_name, ""
    except Exception as exc:
        if fallback_lat is None or fallback_lon is None:
            raise ValueError(
                f"Could not look up '{area_name}' with OpenStreetMap. Check your internet connection or enter coordinates."
            ) from exc

    if fallback_lat is not None and fallback_lon is not None:
        return (float(fallback_lat), float(fallback_lon), float(fallback_radius)), area_name, "Using the supplied fallback coordinates."

    raise ValueError(
        "The place could not be resolved by OpenStreetMap. Try a larger place name, city, and country, or use latitude/longitude."
    )


def local_extract_source(settings):
    source = settings.get("offline_file_bytes")
    file_name = settings.get("offline_file_name", "")
    if source is None:
        path = (
            settings.get("offline_file_path")
            or settings.get("offline_osm_path")
            or settings.get("offline_geojson_path")
        )
        if not path:
            raise ValueError("Choose a local .osm or GeoJSON file to use offline mode.")
        file_path = Path(path)
        if not file_path.is_file():
            raise ValueError(f"Local map extract does not exist: {file_path}")
        file_name = file_path.name
        fingerprint = hashlib.sha256(file_path.read_bytes()).hexdigest()
    else:
        content = bytes(source)
        fingerprint = hashlib.sha256(content).hexdigest()
        suffix = Path(file_name).suffix.lower()
        if suffix not in {".osm", ".geojson", ".json"}:
            if content.lstrip().startswith(b"<"):
                suffix = ".osm"
            else:
                suffix = ".geojson"
        file_path = LOCAL_UPLOAD_PATHS.get(fingerprint)
        if file_path is None:
            file_path = Path(LOCAL_UPLOAD_DIR.name) / f"{fingerprint}{suffix}"
            file_path.write_bytes(content)
            LOCAL_UPLOAD_PATHS[fingerprint] = file_path

    extension = Path(file_name or file_path.name).suffix.lower()
    if extension == ".pbf":
        raise ValueError("PBF files are not supported yet. Use an OSM XML (.osm) or GeoJSON extract.")
    if extension not in {".osm", ".geojson", ".json"}:
        raise ValueError("Unsupported map extract. Choose an OSM XML (.osm) or GeoJSON (.geojson/.json) file.")
    return file_path, fingerprint, extension


def load_local_extract(settings):
    file_path, fingerprint, extension = local_extract_source(settings)
    if extension == ".osm":
        return file_path, fingerprint

    if fingerprint not in LOCAL_EXTRACT_CACHE:
        try:
            content = file_path.read_bytes()
            document = json.loads(content.decode("utf-8-sig"))
            if document.get("type") != "FeatureCollection":
                raise ValueError("The GeoJSON file must contain a FeatureCollection.")
            rows = []
            for feature in document.get("features", []):
                geometry = feature.get("geometry")
                if geometry is None:
                    continue
                row = dict(feature.get("properties") or {})
                row["geometry"] = shape(geometry)
                rows.append(row)
            if rows:
                extract = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
            else:
                extract = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
            LOCAL_EXTRACT_CACHE[fingerprint] = extract
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"Could not read the local GeoJSON extract: {exc}") from exc
    return LOCAL_EXTRACT_CACHE[fingerprint], fingerprint


def local_xml_polygon(area_name, settings):
    area_query, _, _ = area_to_query(area_name, settings)
    if not isinstance(area_query, tuple):
        return None
    lat, lon, radius = area_query
    center = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326")
    projected_center = ox.projection.project_gdf(center)
    circle = projected_center.geometry.iloc[0].buffer(float(radius))
    return gpd.GeoSeries([circle], crs=projected_center.crs).to_crs("EPSG:4326").iloc[0]


def local_extract_for_area(settings, area_name):
    extract, fingerprint = load_local_extract(settings)
    if not isinstance(extract, gpd.GeoDataFrame):
        raise ValueError("This operation expects a GeoJSON extract.")
    area_query, _, _ = area_to_query(area_name, settings)
    if isinstance(area_query, tuple) and not extract.empty:
        projected = project_to_utm(extract)
        center = gpd.GeoSeries(
            [Point(area_query[1], area_query[0])],
            crs="EPSG:4326",
        ).to_crs(projected.crs).iloc[0]
        region = center.buffer(float(area_query[2]))
        extract = extract.loc[projected.geometry.intersects(region)].copy()
    return extract, fingerprint


def _local_tag_match(row, query_key, query_value):
    matching_keys = [key for key in row.index if key.startswith(query_key[:-1])] if query_key.endswith("*") else [query_key]
    for key in matching_keys:
        value = row.get(key)
        if pd.isna(value) if not isinstance(value, (list, dict)) else False:
            continue
        if query_value is True:
            if value is not None and value != "":
                return True
        elif isinstance(query_value, list):
            if str(value) in {str(item) for item in query_value}:
                return True
        elif str(value) == str(query_value):
            return True
    return False


def local_features_for_tags(extract, tags):
    if extract.empty:
        return extract.copy()
    mask = pd.Series(False, index=extract.index)
    for key, value in tags.items():
        mask |= extract.apply(lambda row: _local_tag_match(row, key, value), axis=1)
    return extract.loc[mask].copy()


def cache_is_enabled(settings):
    return bool(default_settings(settings or {}).get("cache_downloads", True))


def describe_overpass_error(error):
    """Convert provider responses into brief, readable status text."""
    message = str(error).lower()
    if "429" in message or "rate limit" in message:
        return "rate limited; wait before trying again"
    if "502" in message or "504" in message or "at capacity" in message or "query workers" in message:
        return "server overloaded; try again later"
    if "timed out" in message or "timeout" in message:
        return "request timed out"
    if "name resolution" in message or "getaddrinfo failed" in message:
        return "DNS lookup failed"
    if "connection" in message:
        return "connection failed"
    return "request failed"


def run_overpass_request(request_func, *args, settings=None, **kwargs):
    """Try configured public Overpass instances, remembering recent failures."""
    global ACTIVE_OVERPASS_URL

    settings = default_settings(settings or {})
    endpoints = settings.get("overpass_endpoints") or OVERPASS_ENDPOINTS
    now = time.monotonic()
    ordered_endpoints = [ACTIVE_OVERPASS_URL] + [
        endpoint for endpoint in endpoints if endpoint != ACTIVE_OVERPASS_URL
    ]
    errors = []

    for endpoint in ordered_endpoints:
        if FAILED_OVERPASS_UNTIL.get(endpoint, 0) > now:
            continue

        ox.settings.overpass_url = endpoint
        try:
            result = request_func(*args, **kwargs)
            ACTIVE_OVERPASS_URL = endpoint
            FAILED_OVERPASS_UNTIL.pop(endpoint, None)
            FAILED_OVERPASS_REASON.pop(endpoint, None)
            return result
        except Exception as exc:
            reason = describe_overpass_error(exc)
            errors.append(f"{endpoint}: {reason}")
            cooldown_seconds = 300 if reason in {
                "rate limited; wait before trying again",
                "server overloaded; try again later",
            } else 120 if reason == "request timed out" else 60
            FAILED_OVERPASS_UNTIL[endpoint] = time.monotonic() + cooldown_seconds
            FAILED_OVERPASS_REASON[endpoint] = reason

    if errors:
        raise RuntimeError(
            "All configured public Overpass services failed. " + " | ".join(errors)
        )

    # Do not retry failed instances once per feature layer; report the last
    # known status and let the user retry after the cooldown.
    recent_errors = [
        f"{endpoint}: {FAILED_OVERPASS_REASON.get(endpoint, 'temporarily unavailable')}"
        for endpoint in ordered_endpoints
    ]
    raise RuntimeError(
        "All configured public Overpass services recently failed. "
        "To avoid repeating slow requests, try again in a few minutes. "
        + " | ".join(recent_errors)
    )


def download_features(area_name: str, tags: dict, settings=None):
    ensure_dirs()
    settings = default_settings(settings or {})
    if settings.get("offline_mode"):
        try:
            source_path, fingerprint, extension = local_extract_source(settings)
            cache_tags = {"tags": tags, "extract": fingerprint}
            if cache_is_enabled(settings):
                cache_path = CACHE_DIR / f"{make_cache_key('offline-features-v1', area_name, cache_tags)}.pkl"
                cached = load_pickle(cache_path)
                if cached is not None:
                    return cached
            if extension == ".osm":
                polygon = local_xml_polygon(area_name, settings)
                try:
                    features = ox.features_from_xml(source_path, polygon=polygon, tags=tags)
                except Exception as exc:
                    if "No matching features" not in str(exc):
                        raise
                    features = gpd.GeoDataFrame(
                        columns=["geometry"],
                        geometry="geometry",
                        crs="EPSG:4326",
                    )
            else:
                extract, _ = local_extract_for_area(settings, area_name)
                features = local_features_for_tags(extract, tags)
            features = safe_geo_dataframe(features)
            if cache_is_enabled(settings):
                save_pickle(cache_path, features)
            return features
        except Exception as exc:
            DOWNLOAD_ERRORS.append(f"Offline map feature query failed: {exc}")
            return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    cache_key = make_cache_key("features-v2", area_name, tags)
    cache_path = CACHE_DIR / f"{cache_key}.pkl"
    if cache_is_enabled(settings):
        cached = load_pickle(cache_path)
        if cached is not None:
            return cached

    try:
        area_query, _, _ = area_to_query(area_name, settings)
        if isinstance(area_query, tuple):
            gdf = run_overpass_request(
                ox.features_from_point,
                (area_query[0], area_query[1]),
                settings=settings,
                dist=area_query[2],
                tags=tags,
            )
        else:
            gdf = run_overpass_request(
                ox.features_from_place,
                area_query,
                settings=settings,
                tags=tags,
            )
    except Exception as exc:
        DOWNLOAD_ERRORS.append(f"OpenStreetMap feature query failed: {exc}")
        gdf = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
        return gdf

    gdf = safe_geo_dataframe(gdf)
    if cache_is_enabled(settings):
        save_pickle(cache_path, gdf)
    return gdf


def download_road_graph(area_name: str, settings=None):
    ensure_dirs()
    settings = default_settings(settings or {})
    if settings.get("offline_mode"):
        try:
            source_path, fingerprint, extension = local_extract_source(settings)
            cache_path = CACHE_DIR / f"{make_cache_key('offline-roads-v1', area_name, {'extract': fingerprint})}.pkl"
            if cache_is_enabled(settings):
                cached = load_pickle(cache_path)
                if cached is not None:
                    return cached
            if extension == ".osm":
                graph = ox.graph_from_xml(source_path, simplify=True, retain_all=True)
                roads = ox.graph_to_gdfs(graph, nodes=False, edges=True)
                polygon = local_xml_polygon(area_name, settings)
                if polygon is not None and not roads.empty:
                    roads = roads.loc[roads.geometry.intersects(polygon)].copy()
            else:
                extract, _ = local_extract_for_area(settings, area_name)
                roads = extract.loc[
                    extract.get("highway", pd.Series(index=extract.index, dtype=object)).notna()
                    & extract.geometry.geom_type.isin(["LineString", "MultiLineString"])
                ].copy()
            roads = safe_geo_dataframe(roads)
            if cache_is_enabled(settings):
                save_pickle(cache_path, roads)
            return safe_geo_dataframe(roads)
        except Exception as exc:
            DOWNLOAD_ERRORS.append(f"Offline map road selection failed: {exc}")
            return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    cache_key = make_cache_key("roads-v2", area_name, {"network_type": "drive"})
    cache_path = CACHE_DIR / f"{cache_key}.pkl"
    if cache_is_enabled(settings):
        cached = load_pickle(cache_path)
        if cached is not None:
            return cached

    try:
        area_query, _, _ = area_to_query(area_name, settings)
        if isinstance(area_query, tuple):
            graph = run_overpass_request(
                ox.graph_from_point,
                (area_query[0], area_query[1]),
                settings=settings,
                dist=area_query[2],
                network_type="drive",
            )
        else:
            graph = run_overpass_request(
                ox.graph_from_place,
                area_query,
                settings=settings,
                network_type="drive",
            )
        roads = ox.graph_to_gdfs(graph, nodes=False, edges=True)
    except Exception as exc:
        DOWNLOAD_ERRORS.append(f"OpenStreetMap road download failed: {exc}")
        roads = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
        return roads

    roads = safe_geo_dataframe(roads)
    if cache_is_enabled(settings):
        save_pickle(cache_path, roads)
    return roads


def project_to_utm(gdf):
    gdf = safe_geo_dataframe(gdf)
    if gdf.empty:
        return gdf
    if gdf.crs is None:
        gdf.set_crs(4326, inplace=True)
    if gdf.crs.is_geographic:
        return ox.projection.project_gdf(gdf)
    return gdf


def point_to_latlon(point, crs):
    location = gpd.GeoSeries([point], crs=crs).to_crs("EPSG:4326").iloc[0]
    return float(location.y), float(location.x)


def nearest_distance(point, gdf):
    if gdf is None or getattr(gdf, "empty", True):
        return float("inf")
    if isinstance(point, tuple):
        point = Point(point[1], point[0])
    try:
        values = gdf.geometry.distance(point)
        if values.empty:
            return float("inf")
        return float(values.min())
    except Exception:
        return float("inf")


def street_view_link(lat, lon):
    return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"


def place_score(distance_m, speed_kmh, lanes, place_type, gap_distance_m):
    distance_score = min(30.0, (distance_m / max(gap_distance_m, 1.0)) * 30.0)
    speed_score = min(25.0, (speed_kmh / 60.0) * 25.0)
    lane_score = min(15.0, (lanes / 4.0) * 15.0) if lanes else 5.0
    type_scores = {
        "school": 30,
        "kindergarten": 30,
        "hospital": 30,
        "bus_stop": 20,
        "station": 20,
        "market": 15,
        "crossing": 10,
        "default": 10,
    }
    place_score_value = type_scores.get(str(place_type).lower(), type_scores["default"])
    total = min(100.0, round(distance_score + speed_score + lane_score + place_score_value, 1))
    return float(total)


def _first_tag_value(value, fallback=None):
    if value is None:
        return fallback
    if isinstance(value, (list, tuple, set)) or (
        hasattr(value, "tolist") and not isinstance(value, (str, bytes))
    ):
        values = value.tolist() if hasattr(value, "tolist") else value
        for item in values:
            result = _first_tag_value(item)
            if result is not None:
                return result
        return fallback
    missing = pd.isna(value)
    if not hasattr(missing, "__len__") and bool(missing):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return value


def highway_roads(roads):
    roads = safe_geo_dataframe(roads)
    if roads.empty or "highway" not in roads.columns:
        return roads.iloc[0:0].copy()
    return roads.loc[roads["highway"].apply(lambda value: _first_tag_value(value) is not None)].copy()


def nearest_highway_road(point, roads):
    roads = highway_roads(roads)
    if roads.empty:
        return None
    distances = roads.geometry.distance(point)
    if distances.empty:
        return None
    return roads.loc[distances.idxmin()]


def grade_separation_note(road, roads=None, point=None):
    if road is None:
        return ""
    bridge = str(_first_tag_value(road.get("bridge"), "")).strip().lower()
    layer_value = _first_tag_value(road.get("layer"))
    try:
        raised_layer = float(str(layer_value).split(";")[0]) >= 1 if layer_value is not None else False
    except ValueError:
        raised_layer = False
    name = " ".join(
        str(_first_tag_value(road.get(tag), ""))
        for tag in ("name", "bridge:name", "destination")
    ).lower()
    highway = str(_first_tag_value(road.get("highway"), "")).lower()
    bridge_nearby = False
    if highway == "trunk" and roads is not None and not roads.empty and point is not None:
        bridges = roads.loc[
            roads.apply(
                lambda row: str(_first_tag_value(row.get("bridge"), "")).lower() in {"yes", "true", "1"}
                or "flyover" in str(_first_tag_value(row.get("name"), "")).lower(),
                axis=1,
            )
        ]
        bridge_nearby = nearest_distance(point, bridges) <= 40
    is_grade_separated = (
        bridge in {"yes", "true", "1"}
        or raised_layer
        or "flyover" in name
        or (highway == "trunk" and ("bridge" in name or bridge_nearby))
    )
    if not is_grade_separated:
        return ""
    return (
        "This place may be on or near a flyover or a grade-separated road. "
        "A signalised crossing may not be possible. Check for a foot overbridge or subway, "
        "and verify on Street View."
    )


def feature_markers(features, analysis_name, crs=None):
    if features is None or features.empty:
        return pd.DataFrame(columns=["analysis", "place name", "place type", "lat", "lon", "is_gap"])
    markers = []
    source_crs = features.crs if features.crs is not None else crs
    if source_crs is None:
        raise ValueError(f"{analysis_name} mapped features have no coordinate reference system")
    for _, row in features.iterrows():
        point = row.geometry
        lat, lon = point_to_latlon(point, source_crs)
        name = display_value(_first_tag_value(row.get("name")), f"Unnamed {analysis_name.replace('_', ' ')} feature")
        markers.append({
            "analysis": analysis_name,
            "place name": name,
            "place type": analysis_name.replace("_", " "),
            "lat": lat,
            "lon": lon,
            "is_gap": False,
        })
    return pd.DataFrame(markers)


def set_analysis_metadata(settings, analysis_name, places_checked, mapped_features, roads, low_confidence=False):
    metadata = settings.setdefault("analysis_metadata", {})
    mapped_count = 0 if mapped_features is None else len(mapped_features)
    markers = feature_markers(mapped_features, analysis_name)
    low_data = mapped_count < 15 or (
        places_checked > 0 and mapped_count / places_checked < 0.01
    )
    low_confidence = low_confidence or low_data
    metadata[analysis_name] = {
        "places_checked": int(places_checked),
        "mapped_feature_count": int(mapped_count),
        "low_confidence": bool(low_confidence),
        "low_data": bool(low_data),
        "confidence": "low confidence" if low_confidence else "normal",
        "map_roads": roads.to_crs("EPSG:4326") if roads is not None and not roads.empty else roads,
        "existing_markers": markers,
    }


def score_component_values(distance_m, speed_kmh, lanes, place_type):
    type_risk = {
        "school": 1.0,
        "kindergarten": 1.0,
        "hospital": 1.0,
        "bus_stop": 0.75,
        "station": 0.75,
        "market": 0.5,
        "crossing": 0.25,
    }
    return {
        "score_distance_component": float(distance_m),
        "score_speed_component": float(speed_kmh),
        "score_lanes_component": float(lanes),
        "score_place_component": type_risk.get(str(place_type).lower(), 0.25),
    }


def choose_road_speed(road_type, default_speed=30):
    type_map = {
        "motorway": 60,
        "trunk": 60,
        "primary": 50,
        "secondary": 40,
        "tertiary": 30,
        "service": 20,
        "residential": 20,
    }
    road_type = str(road_type or "").lower()
    return int(type_map.get(road_type, default_speed))


def choose_lane_count(road_type, fallback=2):
    type_map = {
        "motorway": 4,
        "trunk": 4,
        "primary": 3,
        "secondary": 2,
        "tertiary": 2,
        "service": 2,
        "residential": 2,
    }
    road_type = str(road_type or "").lower()
    return int(type_map.get(road_type, fallback))


def road_speed_lanes(road, default_speed=30):
    road_type = _first_tag_value(road.get("highway"), "secondary")

    speed = None
    raw_speed = _first_tag_value(road.get("maxspeed"))
    if raw_speed is not None and not pd.isna(raw_speed):
        match = re.search(r"\d+(?:\.\d+)?", str(raw_speed))
        if match:
            speed = float(match.group())
            if "mph" in str(raw_speed).lower():
                speed *= 1.60934

    lanes = None
    raw_lanes = _first_tag_value(road.get("lanes"))
    if raw_lanes is not None and not pd.isna(raw_lanes):
        match = re.search(r"\d+(?:\.\d+)?", str(raw_lanes))
        if match:
            lanes = int(float(match.group()))

    if speed is None:
        speed = choose_road_speed(road_type, default_speed=default_speed)
    if lanes is None:
        lanes = choose_lane_count(road_type, fallback=2)
    return int(round(speed)), lanes


def append_missing_columns(df, columns):
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df


def make_gap_map(
    df: pd.DataFrame,
    center_lat: float | None = None,
    center_lon: float | None = None,
    roads: gpd.GeoDataFrame | None = None,
    analysis_names=None,
    focus_rank=None,
):
    focus_row = None
    if focus_rank is not None and not df.empty:
        gap_rows = df.loc[df.get("is_gap", pd.Series(True, index=df.index)).fillna(False).astype(bool)]
        rank_column = "map_rank" if "map_rank" in gap_rows else "rank"
        if rank_column in gap_rows:
            focused_rows = gap_rows.loc[
                pd.to_numeric(gap_rows[rank_column], errors="coerce") == int(focus_rank)
            ]
            if not focused_rows.empty:
                focus_row = focused_rows.iloc[0]
                center_lat = float(focus_row["lat"])
                center_lon = float(focus_row["lon"])

    if center_lat is None or center_lon is None:
        if not df.empty and {"lat", "lon"}.issubset(df.columns):
            center_lat = float(df["lat"].mean())
            center_lon = float(df["lon"].mean())
        else:
            center_lat = 13.0
            center_lon = 80.2

    my_map = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=17 if focus_row is not None else 15,
        tiles="OpenStreetMap",
    )
    road_layer = folium.FeatureGroup(name="Roads", show=True)
    if roads is not None and not roads.empty:
        road_data = roads.to_crs("EPSG:4326") if roads.crs is not None else roads
        folium.GeoJson(
            road_data.to_json(),
            style_function=lambda feature: {"color": "#777777", "weight": 1, "opacity": 0.7},
        ).add_to(road_layer)
    road_layer.add_to(my_map)

    if analysis_names is None:
        analysis_names = sorted(
            set(df.get("analysis", pd.Series(dtype=str)).dropna().astype(str))
        )
    for analysis_name in analysis_names:
        analysis_rows = (
            df.loc[df["analysis"].astype(str) == str(analysis_name)]
            if not df.empty and "analysis" in df.columns
            else pd.DataFrame()
        )
        existing_layer = folium.FeatureGroup(name=f"{analysis_name}: existing features", show=True)
        gap_layer = folium.FeatureGroup(name=f"{analysis_name}: gaps", show=True)
        for _, row in analysis_rows.iterrows():
            is_gap = bool(row.get("is_gap", True))
            lat = float(row.get("lat", center_lat))
            lon = float(row.get("lon", center_lon))
            score = float(row.get("score", 0) or 0)
            name = display_place_name(row)
            place_type = display_value(row.get("place type"), "Unknown")
            road_name = display_value(row.get("road name"), "Unnamed road")
            rank = row.get("map_rank", row.get("rank"))
            rank_text = f"#{int(rank)} " if is_gap and pd.notna(rank) and int(rank) <= 10 else ""
            color = "#d73027" if is_gap else "#1a9850"
            popup = (
                f"<b>{rank_text}{name}</b><br>"
                f"Type: {place_type}<br>"
                f"Coordinates: {lat:.6f}, {lon:.6f}<br>"
                f"Road: {road_name}<br>"
            )
            merged_count = pd.to_numeric(row.get("merged from N mapped points", 1), errors="coerce")
            if pd.notna(merged_count) and int(merged_count) > 1:
                popup += f"Merged from {int(merged_count)} mapped points<br>"
            if is_gap:
                distance = display_value(row.get("distance to nearest"), "Not mapped")
                popup += (
                    f"Distance to feature: {distance}"
                    f"{' m' if distance != 'Not mapped' else ''}<br>"
                    f"Score: {score:.1f}<br>"
                    f"Confidence: {display_value(row.get('confidence'), 'normal')}<br>"
                    f"Fix: {display_value(row.get('suggested fix'), 'Review the site')}"
                )
                road_note = display_value(row.get("road note"), "")
                if road_note:
                    popup += f"<br>{road_note}"
            folium.CircleMarker(
                location=[lat, lon],
                radius=5 if is_gap else 6,
                color=color,
                weight=1,
                fill_color=color,
                fill_opacity=0.5 if is_gap else 0.85,
                popup=folium.Popup(
                    popup,
                    max_width=380,
                    show=(
                        is_gap
                        and focus_row is not None
                        and pd.notna(rank)
                        and int(rank) == int(focus_rank)
                    ),
                ),
                tooltip=f"{rank_text}{name}",
            ).add_to(gap_layer if is_gap else existing_layer)
            if is_gap and pd.notna(rank) and int(rank) <= 10:
                folium.Marker(
                    location=[lat, lon],
                    icon=folium.DivIcon(
                        html=(
                            '<div style="font-size:10px;font-weight:bold;color:#111;'
                            'background:#fff;border:1px solid #d73027;border-radius:8px;'
                            'width:18px;height:18px;text-align:center;line-height:16px;">'
                            f"{int(rank)}</div>"
                        )
                    ),
                ).add_to(gap_layer)
        existing_layer.add_to(my_map)
        gap_layer.add_to(my_map)

    legend = """
    <div style="position: fixed; bottom: 20px; right: 20px; background: white; padding: 8px 12px; border: 1px solid #ccc; border-radius: 8px; font-size: 12px;">
      <b>Legend</b><br>
      Green = existing crossings / covered places<br>
      Red = possible crossing gaps<br>
      Grey = mapped roads
    </div>
    """
    my_map.get_root().html.add_child(folium.Element(legend))
    folium.LayerControl().add_to(my_map)
    return my_map


def display_value(value, fallback):
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def display_place_name(row):
    place_type = display_value(row.get("place type"), "place").replace("_", " ")
    name = display_value(row.get("place name"), f"Unnamed {place_type}")
    if name.lower() in {"unnamed", "unnamed place", "unknown"}:
        return f"Unnamed {place_type}"
    return name


def _short_chart_name(value):
    value = display_value(value, "Unnamed")
    value = value.replace("_", " ")
    ascii_name = value.encode("ascii", "ignore").decode("ascii").strip()
    if not ascii_name:
        return "Unnamed"
    return ascii_name[:22]


def score_results(df: pd.DataFrame):
    component_columns = [
        "score_distance_component",
        "score_speed_component",
        "score_lanes_component",
        "score_place_component",
    ]
    if df.empty or any(column not in df.columns for column in component_columns):
        return df
    component_ranks = pd.DataFrame(index=df.index)
    for column in component_columns:
        values = pd.to_numeric(df[column], errors="coerce").fillna(0)
        component_ranks[column] = values.rank(method="first", pct=True)
    percentile_names = {
        component_columns[0]: "distance percentile",
        component_columns[1]: "speed percentile",
        component_columns[2]: "lanes percentile",
        component_columns[3]: "place type percentile",
    }
    for column, name in percentile_names.items():
        df[name] = component_ranks[column].round(4)
    weighted = (
        component_ranks[component_columns[0]] * 0.40
        + component_ranks[component_columns[1]] * 0.25
        + component_ranks[component_columns[2]] * 0.20
        + component_ranks[component_columns[3]] * 0.15
    )
    df["weighted percentile score"] = weighted.round(4)
    minimum = weighted.min()
    maximum = weighted.max()
    if maximum == minimum:
        final_percentile = weighted.rank(method="first", pct=True)
    else:
        final_percentile = (weighted - minimum) / (maximum - minimum)
    df["score"] = (20 + 80 * final_percentile).round(1)
    return df


def save_summary_report(path: Path, df: pd.DataFrame, area_name: str, settings):
    if df.empty:
        text = "No gaps found in this area.\n"
    else:
        df = df.head(int(settings.get("top_n", 5)))
        lines = [
            f"# Top gap summary for {area_name}",
            "",
            f"- Places checked: {int(settings.get('places_checked', 0) or 0)}",
            f"- Gaps found: {len(df)}",
            "- Map notes: OpenStreetMap data may be incomplete. Results should be checked on Street View.",
            "",
        ]
        for _, row in df.iterrows():
            lines.append(f"## Rank {int(row.get('rank', 0))}: {display_value(row.get('place name'), 'Unnamed place')}")
            lines.append(f"Why it is risky: {display_value(row.get('reason'), 'Risk factors need checking.')}")
            lines.append(f"Suggested fix: {display_value(row.get('suggested fix'), 'Review the site and design an appropriate safety feature.')}")
            lines.append(f"Street View: {display_value(row.get('street view link'), 'Not available')}")
            lines.append("")
        text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")


def save_chart_png(path: Path, df: pd.DataFrame):
    top = df.head(10).copy()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))

    if not top.empty:
        top = top.iloc[::-1].copy()
        labels = [
            f"#{int(row.get('rank', index + 1))} {_short_chart_name(row.get('place name'))}"
            for index, (_, row) in enumerate(top.iterrows())
        ]
        ax1.barh(labels, pd.to_numeric(top["score"], errors="coerce"), color="#d73027")
        ax1.set_title("Top gap scores")
        ax1.set_xlabel("Score (20-100)")

        counts = top.groupby("place type").size().sort_values()
        type_labels = [_short_chart_name(item) for item in counts.index]
        ax2.barh(type_labels, counts.values, color="#1f77b4")
        ax2.set_title("Gap counts by place type")
    else:
        ax1.text(0.5, 0.5, "No data", ha="center", va="center")
        ax2.text(0.5, 0.5, "No data", ha="center", va="center")

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def build_combined_report(df: pd.DataFrame, area_name: str, settings):
    if df.empty:
        return "No gap results found."
    top = df.head(int(settings.get("top_n", 5)))
    lines = [
        f"# Summary for {area_name}",
        "",
        f"- Number of places checked: {int(settings.get('places_checked', 0) or 0)}",
        f"- Number of gaps found: {len(df)}",
        "- Data note: OpenStreetMap gaps are possible gaps, not proven facts. Check on Street View before design work.",
        "",
    ]
    for _, row in top.iterrows():
        lines.append(f"## Rank {int(row.get('rank', 1))}: {display_value(row.get('place name'), 'Unnamed place')} ({display_value(row.get('place type'), 'Unknown')})")
        lines.append(f"Why it is risky: {display_value(row.get('reason'), 'Risk factors need checking.')}")
        lines.append(f"Suggested fix: {display_value(row.get('suggested fix'), 'Review the site and design an appropriate safety feature.')}")
        lines.append(f"Street View: {display_value(row.get('street view link'), 'Not available')}")
        lines.append("")
    return "\n".join(lines)


def save_outputs_for_area(area_name: str, results: dict, combined: pd.DataFrame, settings: dict):
    ensure_dirs()
    output_files = {}
    combined_path = OUTPUT_DIR / "top_gaps.csv"
    if not combined.empty:
        combined.to_csv(combined_path, index=False)
        output_files["top_gaps_csv"] = str(combined_path)

    summary_path = OUTPUT_DIR / "top_gaps_summary.md"
    summary_text = build_combined_report(combined, area_name, settings)
    summary_path.write_text(summary_text, encoding="utf-8")
    output_files["summary_report"] = str(summary_path)

    verify_path = OUTPUT_DIR / "verify_on_street_view.md"
    verify_lines = [
        "# Street View verification checklist",
        "",
        "| Rank | Place | Street View link | Crossing really missing? (yes/no) | Notes |",
        "|---|---|---|---|---|",
    ]
    for _, row in combined.head(int(settings.get("top_n", 5))).iterrows():
        verify_lines.append(
            f"| {int(row.get('rank', 0))} | {display_value(row.get('place name'), 'Unnamed place')} | {display_value(row.get('street view link'), 'Not available')} |  |  |"
        )
    verify_path.write_text("\n".join(verify_lines), encoding="utf-8")
    output_files["verify_checklist"] = str(verify_path)

    chart_path = OUTPUT_DIR / "summary_chart.png"
    save_chart_png(chart_path, combined)
    output_files["chart_png"] = str(chart_path)

    for name, df in results.items():
        if df.empty:
            continue
        csv_path = OUTPUT_DIR / f"{name}.csv"
        df.to_csv(csv_path, index=False)
        output_files[f"{name}_csv"] = str(csv_path)

    map_path = OUTPUT_DIR / "crossing_gap_map.html"
    map_data = combined
    roads = settings.get("map_roads")
    if not map_data.empty:
        center_lat = float(map_data["lat"].mean())
        center_lon = float(map_data["lon"].mean())
    elif roads is not None and not roads.empty:
        center = roads.to_crs("EPSG:4326").geometry.union_all().centroid
        center_lat, center_lon = float(center.y), float(center.x)
    else:
        center_lat, center_lon = 13.0, 80.2
    map_obj = make_gap_map(map_data, center_lat, center_lon, roads)
    map_obj.save(map_path)
    output_files["map_html"] = str(map_path)

    return output_files


def combine_result_frames(results: dict):
    frames = []
    for name, df in results.items():
        if df is None or getattr(df, "empty", True):
            continue
        frame = df.copy()
        frame["analysis"] = name
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=[
            "rank", "place name", "place type", "lat", "lon", "gap types",
            "gap type count", "average score", "score", "suggested fix",
            "street view link",
        ])
    combined = pd.concat(frames, ignore_index=True)
    combined["_lat_key"] = pd.to_numeric(combined["lat"], errors="coerce").round(6)
    combined["_lon_key"] = pd.to_numeric(combined["lon"], errors="coerce").round(6)
    combined = combined.drop_duplicates(
        subset=["analysis", "_lat_key", "_lon_key"],
        keep="first",
    )
    rows = []
    for _, group in combined.groupby(["_lat_key", "_lon_key"], sort=False, dropna=False):
        gap_types = sorted(set(group["analysis"].astype(str)))
        row = group.iloc[0].drop(labels=["_lat_key", "_lon_key"]).to_dict()
        average_score = pd.to_numeric(group["score"], errors="coerce").mean()
        row["gap types"] = " + ".join(gap_types)
        row["gap type count"] = len(gap_types)
        row["average score"] = round(float(average_score), 1) if pd.notna(average_score) else 20.0
        merged_counts = pd.to_numeric(
            group.get("merged from N mapped points", pd.Series(1, index=group.index)),
            errors="coerce",
        ).fillna(1)
        row["merged from N mapped points"] = int(merged_counts.max())
        row["score"] = row["average score"]
        row["analysis"] = row["gap types"]
        rows.append(row)
    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["gap type count", "average score"], ascending=[False, False]
    ).reset_index(drop=True)
    result["rank"] = range(1, len(result) + 1)
    return result


def save_project_outputs(area_name: str, results: dict, combined: pd.DataFrame, settings: dict, output_dir=None):
    if output_dir is None:
        output_dir = create_run_output_dir(area_name, results.keys())
    output_dir = Path(output_dir)
    output_files = _save_requested_outputs(area_name, results, combined, settings, output_dir)
    return output_files


def _safe_combined_report(df: pd.DataFrame, area_name: str, settings: dict):
    analysis_counts = [
        f"{name}={int(metadata.get('gap_count', 0))}"
        for name, metadata in settings.get("analysis_metadata", {}).items()
    ]
    if df.empty:
        lines = [
            f"# Summary for {area_name}",
            "",
            "- No reliable gap rows were produced.",
            f"- Gap counts by analysis: {', '.join(analysis_counts) or 'none'}",
            "",
        ]
        for name, metadata in settings.get("analysis_metadata", {}).items():
            lines.append(
                f"- {name}: {int(metadata.get('places_checked', 0))} places checked; "
                f"{int(metadata.get('mapped_feature_count', 0))} mapped features; "
                f"{metadata.get('confidence', 'normal')}."
            )
        return "\n".join(lines)
    lines = [
        f"# Summary for {area_name}",
        "",
        f"- Unique places with one or more gap types: {len(df)}",
        f"- Gap counts by analysis: {', '.join(analysis_counts) or 'none'}",
        "- Data note: These are possible gaps, not proven facts. Verify sites before design work.",
        "",
    ]
    for name, metadata in settings.get("analysis_metadata", {}).items():
        lines.append(
            f"- {name}: {int(metadata.get('places_checked', 0))} places checked; "
            f"{int(metadata.get('mapped_feature_count', 0))} mapped features; "
            f"{metadata.get('confidence', 'normal')}."
        )
    lines.append("")
    show_gap_types = len(settings.get("analysis_metadata", {})) > 1
    for _, row in df.head(int(settings.get("top_n", 5))).iterrows():
        lines.append(
            f"## Rank {int(row.get('rank', 1))}: {display_place_name(row)}"
        )
        if show_gap_types:
            lines.append(
                f"Gap types: {display_value(row.get('gap types'), display_value(row.get('place type'), 'Unknown'))} "
                f"({int(row.get('gap type count', 1))})"
            )
        lines.extend([
            f"Why it is risky: {display_value(row.get('reason'), 'Risk factors need checking.')}",
            f"Suggested fix: {display_value(row.get('suggested fix'), 'Review the site.')}",
            f"Street View: {display_value(row.get('street view link'), 'Not available')}",
            "",
        ])
    return "\n".join(lines)


def _save_horizontal_chart(path: Path, df: pd.DataFrame, analysis_names, analysis_results):
    top = df.head(10).copy()
    fig, (score_ax, type_ax) = plt.subplots(1, 2, figsize=(12, 6))
    if not top.empty:
        top = top.iloc[::-1]
        labels = [
            f"#{int(row.get('rank', index + 1))} {_short_chart_name(display_place_name(row))}"
            for index, (_, row) in enumerate(top.iterrows())
        ]
        score_ax.barh(labels, pd.to_numeric(top["score"], errors="coerce"), color="#d73027")
        score_ax.set_title("Top gap scores")
        score_ax.set_xlabel("Score (20-100)")
    else:
        score_ax.text(0.5, 0.5, "No data", ha="center", va="center")
        score_ax.set_title("Top gap scores")

    if len(analysis_names) == 1:
        source = analysis_results.get(analysis_names[0], pd.DataFrame())
        counts = source.groupby("place type").size().sort_values() if not source.empty else pd.Series(dtype=int)
        if analysis_names[0] == "railings":
            counts = counts.drop(index="crossing", errors="ignore")
        if not counts.empty:
            type_ax.barh(
                [_short_chart_name(value) for value in counts.index],
                counts.values,
                color="#1f77b4",
            )
        else:
            type_ax.text(0.5, 0.5, "No data", ha="center", va="center")
        type_ax.set_title("Gap counts by place type")
        type_ax.set_xlabel("Number of places")
    elif not top.empty:
        type_labels = [
            f"#{int(row.get('rank', index + 1))} {_short_chart_name(display_place_name(row))}"
            for index, (_, row) in enumerate(top.iterrows())
        ]
        type_ax.barh(type_labels, pd.to_numeric(top["gap type count"], errors="coerce"), color="#1f77b4")
        type_ax.set_title("Gap types per combined place")
        type_ax.set_xlabel("Number of gap types")
    else:
        type_ax.text(0.5, 0.5, "No data", ha="center", va="center")
        type_ax.set_title("Gap types per combined place")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _save_requested_outputs(area_name: str, results: dict, combined: pd.DataFrame, settings: dict, output_dir: Path):
    ensure_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_files = {}
    if not combined.empty:
        combined_path = output_dir / "top_gaps.csv"
        combined.to_csv(combined_path, index=False)
        output_files["top_gaps_csv"] = str(combined_path)

    summary_path = output_dir / "top_gaps_summary.md"
    summary_path.write_text(_safe_combined_report(combined, area_name, settings), encoding="utf-8")
    output_files["summary_report"] = str(summary_path)

    verify_path = output_dir / "verify_on_street_view.md"
    verify_lines = [
        "# Street View verification checklist",
        "",
        "| Rank | Place | Street View link | Crossing really missing? (yes/no) | Notes |",
        "|---|---|---|---|---|",
    ]
    for _, row in combined.head(int(settings.get("top_n", 5))).iterrows():
        verify_lines.append(
            f"| {int(row.get('rank', 0))} | {display_value(row.get('place name'), 'Unnamed place')} | "
            f"{display_value(row.get('street view link'), 'Not available')} |  |  |"
        )
    verify_path.write_text("\n".join(verify_lines), encoding="utf-8")
    output_files["verify_checklist"] = str(verify_path)

    chart_path = output_dir / "summary_chart.png"
    _save_horizontal_chart(chart_path, combined, list(results), results)
    output_files["chart_png"] = str(chart_path)

    for name, result_df in results.items():
        if not result_df.empty:
            csv_path = output_dir / f"{name}.csv"
            result_df.to_csv(csv_path, index=False)
            output_files[f"{name}_csv"] = str(csv_path)

    metadata_by_analysis = settings.get("analysis_metadata", {})
    map_rows = []
    road_frames = []
    rank_by_place = {
        (round(float(row["lat"]), 6), round(float(row["lon"]), 6)): int(row["rank"])
        for _, row in combined.iterrows()
        if pd.notna(row.get("lat")) and pd.notna(row.get("lon"))
    }
    for name, result_df in results.items():
        metadata = metadata_by_analysis.get(name, {})
        if not result_df.empty:
            gap_rows = result_df.copy()
            gap_rows["analysis"] = name
            gap_rows["is_gap"] = True
            gap_rows["map_rank"] = [
                rank_by_place.get((round(float(row["lat"]), 6), round(float(row["lon"]), 6)))
                for _, row in gap_rows.iterrows()
            ]
            map_rows.append(gap_rows)
        existing = metadata.get("existing_markers")
        if isinstance(existing, pd.DataFrame) and not existing.empty:
            existing_rows = existing.copy()
            existing_rows["analysis"] = name
            existing_rows["is_gap"] = False
            map_rows.append(existing_rows)
        roads_for_analysis = metadata.get("map_roads")
        if roads_for_analysis is not None and not roads_for_analysis.empty:
            road_frames.append(roads_for_analysis.to_crs("EPSG:4326"))
    map_data = pd.concat(map_rows, ignore_index=True) if map_rows else pd.DataFrame()
    roads = gpd.GeoDataFrame(
        pd.concat(road_frames, ignore_index=True) if road_frames else {"geometry": []},
        geometry="geometry",
        crs="EPSG:4326",
    )
    if not map_data.empty:
        center_lat = float(map_data["lat"].mean())
        center_lon = float(map_data["lon"].mean())
    elif roads is not None and not roads.empty:
        roads_wgs84 = roads.to_crs("EPSG:4326") if roads.crs is not None else roads
        center = roads_wgs84.geometry.union_all().centroid
        center_lat, center_lon = float(center.y), float(center.x)
    else:
        center_lat, center_lon = 13.0, 80.2
    map_path = output_dir / "crossing_gap_map.html"
    make_gap_map(
        map_data,
        center_lat,
        center_lon,
        roads,
        analysis_names=list(metadata_by_analysis),
    ).save(map_path)
    output_files["map_html"] = str(map_path)
    output_files["run_directory"] = str(output_dir)
    return output_files
    
    
def save_chart_png(path: Path, df: pd.DataFrame):
    top = df.head(10).copy()
    fig, (score_ax, type_ax) = plt.subplots(1, 2, figsize=(12, 6))
    if not top.empty:
        top = top.iloc[::-1]
        labels = [
            f"#{int(row.get('rank', index + 1))} {_short_chart_name(row.get('place name'))}"
            for index, (_, row) in enumerate(top.iterrows())
        ]
        score_ax.barh(labels, pd.to_numeric(top["score"], errors="coerce"), color="#d73027")
        score_ax.set_title("Top gap scores")
        score_ax.set_xlabel("Score (20-100)")
        counts = top.groupby("place type").size().sort_values()
        type_ax.barh([_short_chart_name(value) for value in counts.index], counts.values, color="#1f77b4")
        type_ax.set_title("Gap counts by place type")
    else:
        score_ax.text(0.5, 0.5, "No data", ha="center", va="center")
        type_ax.text(0.5, 0.5, "No data", ha="center", va="center")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def build_combined_report(df: pd.DataFrame, area_name: str, settings):
    if df.empty:
        return (
            f"# Summary for {area_name}\n\n"
            f"- Number of places checked: {int(settings.get('places_checked', 0) or 0)}\n"
            "- Number of gaps found: 0\n"
        )
    top = df.head(int(settings.get("top_n", 5)))
    lines = [
        f"# Summary for {area_name}",
        "",
        f"- Number of places checked: {int(settings.get('places_checked', 0) or 0)}",
        f"- Number of gaps found: {len(df)}",
        "- Data note: These are possible gaps, not proven facts. Check them on Street View.",
        "",
    ]
    for _, row in top.iterrows():
        lines.extend([
            f"## Rank {int(row.get('rank', 1))}: {display_value(row.get('place name'), 'Unnamed place')} ({display_value(row.get('place type'), 'Unknown')})",
            f"Why it is risky: {display_value(row.get('reason'), 'Risk factors need checking.')}",
            f"Suggested fix: {display_value(row.get('suggested fix'), 'Review the site and design an appropriate safety feature.')}",
            f"Street View: {display_value(row.get('street view link'), 'Not available')}",
            "",
        ])
    return "\n".join(lines)


def save_outputs_for_area(area_name: str, results: dict, combined: pd.DataFrame, settings: dict):
    ensure_dirs()
    output_files = {}
    if not combined.empty:
        combined_path = OUTPUT_DIR / "top_gaps.csv"
        combined.to_csv(combined_path, index=False)
        output_files["top_gaps_csv"] = str(combined_path)

    summary_path = OUTPUT_DIR / "top_gaps_summary.md"
    summary_path.write_text(build_combined_report(combined, area_name, settings), encoding="utf-8")
    output_files["summary_report"] = str(summary_path)

    verify_path = OUTPUT_DIR / "verify_on_street_view.md"
    verify_lines = [
        "# Street View verification checklist",
        "",
        "| Rank | Place | Street View link | Crossing really missing? (yes/no) | Notes |",
        "|---|---|---|---|---|",
    ]
    for _, row in combined.head(int(settings.get("top_n", 5))).iterrows():
        verify_lines.append(
            f"| {int(row.get('rank', 0))} | {display_value(row.get('place name'), 'Unnamed place')} | "
            f"{display_value(row.get('street view link'), 'Not available')} |  |  |"
        )
    verify_path.write_text("\n".join(verify_lines), encoding="utf-8")
    output_files["verify_checklist"] = str(verify_path)

    chart_path = OUTPUT_DIR / "summary_chart.png"
    save_chart_png(chart_path, combined)
    output_files["chart_png"] = str(chart_path)

    for name, result_df in results.items():
        if not result_df.empty:
            csv_path = OUTPUT_DIR / f"{name}.csv"
            result_df.to_csv(csv_path, index=False)
            output_files[f"{name}_csv"] = str(csv_path)

    roads = settings.get("map_roads")
    markers = settings.get("map_markers")
    map_rows = []
    if isinstance(markers, pd.DataFrame) and not markers.empty:
        map_rows.append(markers.loc[~markers["is_gap"].fillna(False)].copy())
    if not combined.empty:
        map_rows.append(combined.copy())
    map_data = pd.concat(map_rows, ignore_index=True) if map_rows else pd.DataFrame()
    if not map_data.empty:
        center_lat = float(map_data["lat"].mean())
        center_lon = float(map_data["lon"].mean())
    elif roads is not None and not roads.empty:
        roads_wgs84 = roads.to_crs("EPSG:4326") if roads.crs is not None else roads
        center = roads_wgs84.geometry.union_all().centroid
        center_lat, center_lon = float(center.y), float(center.x)
    else:
        center_lat, center_lon = 13.0, 80.2
    map_path = OUTPUT_DIR / "crossing_gap_map.html"
    make_gap_map(map_data, center_lat, center_lon, roads).save(map_path)
    output_files["map_html"] = str(map_path)
    return output_files
    legend = """
    <div style="position: fixed; bottom: 20px; right: 20px; background: white; padding: 8px 12px; border: 1px solid #ccc; border-radius: 8px; font-size: 12px;">
      <b>Legend</b><br>
      Green = covered features<br>
      Red = gap locations<br>
      Grey = roads
    </div>
    """
    my_map.get_root().html.add_child(folium.Element(legend))
    folium.LayerControl().add_to(my_map)
    return my_map


def save_summary_report(path: Path, df: pd.DataFrame, area_name: str, settings):
    if df.empty:
        text = "No gaps found in this area.\n"
    else:
        df = df.head(int(settings.get("top_n", 5)))
        lines = [
            f"# Top gap summary for {area_name}",
            "",
            f"- Places checked: {int(settings.get('places_checked', 0) or 0)}",
            f"- Gaps found: {len(df)}",
            "- Map notes: OpenStreetMap data may be incomplete. Results should be checked on Street View.",
            "",
        ]
        for _, row in df.iterrows():
            lines.append(f"## Rank {int(row.get('rank', 0))}: {row.get('place name', 'Unknown')}")
            lines.append(f"Why it is risky: {row.get('reason', 'Missing description')}")
            lines.append(f"Suggested fix: {row.get('suggested fix', 'Missing suggestion')}")
            lines.append(f"Street View: {row.get('street view link', 'Not available')}")
            lines.append("")
        text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")


def save_chart_png(path: Path, df: pd.DataFrame):
    top = df.head(10).copy()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    if not top.empty:
        ax1.bar(top["place name"].astype(str).head(10), top["score"].astype(float), color="#d73027")
        ax1.set_title("Top gap scores")
        ax1.tick_params(axis="x", rotation=45)
        ax1.set_ylabel("Score")

        counts = top.groupby("place type").size()
        ax2.bar(counts.index.astype(str), counts.values, color="#1f77b4")
        ax2.set_title("Gap counts by place type")
        ax2.tick_params(axis="x", rotation=45)
    else:
        ax1.text(0.5, 0.5, "No data", ha="center", va="center")
        ax2.text(0.5, 0.5, "No data", ha="center", va="center")

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def build_combined_report(df: pd.DataFrame, area_name: str, settings):
    if df.empty:
        return "No gap results found."
    top = df.head(int(settings.get("top_n", 5)))
    lines = [
        f"# Summary for {area_name}",
        "",
        f"- Number of places checked: {int(settings.get('places_checked', 0) or 0)}",
        f"- Number of gaps found: {len(df)}",
        "- Data note: OpenStreetMap gaps are possible gaps, not proven facts. Check on Street View before design work.",
        "",
    ]
    for _, row in top.iterrows():
        lines.append(f"## Rank {int(row.get('rank', 1))}: {row.get('place name', 'Unknown')} ({row.get('place type', 'Unknown')})")
        lines.append(f"Why it is risky: {row.get('reason', 'Not available')}")
        lines.append(f"Suggested fix: {row.get('suggested fix', 'Not available')}")
        lines.append(f"Street View: {row.get('street view link', 'Not available')}")
        lines.append("")
    return "\n".join(lines)


def save_outputs_for_area(area_name: str, results: dict, combined: pd.DataFrame, settings: dict):
    ensure_dirs()
    output_files = {}
    combined_path = OUTPUT_DIR / "top_gaps.csv"
    if not combined.empty:
        combined.to_csv(combined_path, index=False)
        output_files["top_gaps_csv"] = str(combined_path)

    summary_path = OUTPUT_DIR / "top_gaps_summary.md"
    summary_text = build_combined_report(combined, area_name, settings)
    summary_path.write_text(summary_text, encoding="utf-8")
    output_files["summary_report"] = str(summary_path)

    verify_path = OUTPUT_DIR / "verify_on_street_view.md"
    verify_lines = [
        "# Street View verification checklist",
        "",
        "| Rank | Place | Street View link | Crossing really missing? (yes/no) | Notes |",
        "|---|---|---|---|---|",
    ]
    for _, row in combined.head(int(settings.get("top_n", 5))).iterrows():
        verify_lines.append(
            f"| {int(row.get('rank', 0))} | {row.get('place name', 'Unknown')} | {row.get('street view link', 'Not available')} |  |  |"
        )
    verify_path.write_text("\n".join(verify_lines), encoding="utf-8")
    output_files["verify_checklist"] = str(verify_path)

    chart_path = OUTPUT_DIR / "summary_chart.png"
    save_chart_png(chart_path, combined)
    output_files["chart_png"] = str(chart_path)

    for name, df in results.items():
        if df.empty:
            continue
        csv_path = OUTPUT_DIR / f"{name}.csv"
        df.to_csv(csv_path, index=False)
        output_files[f"{name}_csv"] = str(csv_path)

    map_path = OUTPUT_DIR / "crossing_gap_map.html"
    if not combined.empty:
        center_lat = float(combined["lat"].mean())
        center_lon = float(combined["lon"].mean())
        roads = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
        map_obj = make_gap_map(combined, center_lat, center_lon, roads)
        map_obj.save(map_path)
    else:
        html = """
        <html><body>
        <h3>No map results available</h3>
        <p>OpenStreetMap data was not found for this area, or the network is unavailable.</p>
        </body></html>
        """
        map_path.write_text(html, encoding="utf-8")
    output_files["map_html"] = str(map_path)

    return output_files


def combine_result_frames(results: dict):
    frames = []
    for name, df in results.items():
        if df is None or getattr(df, "empty", True):
            continue
        frame = df.copy()
        frame["analysis"] = name
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["rank", "place name", "place type", "lat", "lon", "score", "suggested fix", "street view link"])
    combined = pd.concat(frames, ignore_index=True)
    combined["_lat_key"] = pd.to_numeric(combined["lat"], errors="coerce").round(6)
    combined["_lon_key"] = pd.to_numeric(combined["lon"], errors="coerce").round(6)
    combined = combined.drop_duplicates(
        subset=["analysis", "_lat_key", "_lon_key"],
        keep="first",
    )
    rows = []
    for _, group in combined.groupby(["_lat_key", "_lon_key"], sort=False, dropna=False):
        gap_types = sorted(set(group["analysis"].astype(str)))
        row = group.iloc[0].drop(labels=["_lat_key", "_lon_key"]).to_dict()
        average_score = pd.to_numeric(group["score"], errors="coerce").mean()
        row["gap types"] = " + ".join(gap_types)
        row["gap type count"] = len(gap_types)
        row["average score"] = round(float(average_score), 1) if pd.notna(average_score) else 20.0
        merged_counts = pd.to_numeric(
            group.get("merged from N mapped points", pd.Series(1, index=group.index)),
            errors="coerce",
        ).fillna(1)
        row["merged from N mapped points"] = int(merged_counts.max())
        row["score"] = row["average score"]
        row["analysis"] = row["gap types"]
        rows.append(row)
    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["gap type count", "average score"], ascending=[False, False]
    ).reset_index(drop=True)
    result["rank"] = range(1, len(result) + 1)
    return result


def save_project_outputs(area_name: str, results: dict, combined: pd.DataFrame, settings: dict, output_dir=None):
    if output_dir is None:
        output_dir = create_run_output_dir(area_name, results.keys())
    output_dir = Path(output_dir)
    output_files = _save_requested_outputs(area_name, results, combined, settings, output_dir)
    return output_files
