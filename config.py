"""Default settings for the road safety analysis project."""

AREA_NAME = "Guindy, Chennai, India"
GAP_DISTANCE_M = 100
TOP_N = 5
ROAD_TYPES = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
]
AREA_SIZE_LIMIT_M = 3000
SAVE_DOWNLOAD_CACHE = True
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]
CALMING_DISTANCE_M = 60
SIGN_DISTANCE_M = 50
RAILING_DISTANCE_M = 40
ANALYSIS_CHOICES = ["crossings", "speed_breakers", "signs", "railings"]
DEFAULT_ANALYSES = ["crossings"]


def default_settings(overrides=None):
    settings = {
        "area_name": AREA_NAME,
        "gap_distance_m": GAP_DISTANCE_M,
        "top_n": TOP_N,
        "road_types": ROAD_TYPES,
        "area_size_limit_m": AREA_SIZE_LIMIT_M,
        "cache_downloads": SAVE_DOWNLOAD_CACHE,
        "overpass_endpoints": OVERPASS_ENDPOINTS,
        "calming_distance_m": CALMING_DISTANCE_M,
        "sign_distance_m": SIGN_DISTANCE_M,
        "railing_distance_m": RAILING_DISTANCE_M,
    }
    if overrides:
        settings.update(overrides)
    return settings
