"""Command-line entry point for the missing pedestrian crossing finder."""

from __future__ import annotations

import argparse
from analysis import run_analysis
from config import default_settings


def parse_args():
    parser = argparse.ArgumentParser(description="Find unsafe road crossing gaps near important places.")
    parser.add_argument("area_name", nargs="?", default="Guindy, Chennai, India", help="Place name, city, or coordinates like '13.0,80.2'.")
    parser.add_argument("--analyse", default="crossings", help="Comma-separated list: crossings,speed_breakers,signs,railings")
    parser.add_argument("--gap-distance", type=float, default=None, help="Distance in metres for a missing crossing or feature.")
    parser.add_argument("--top-n", type=int, default=None, help="Number of top gaps to report.")
    parser.add_argument("--lat", type=float, default=None, help="Optional latitude used when the place name cannot be found.")
    parser.add_argument("--lon", type=float, default=None, help="Optional longitude used when the place name cannot be found.")
    parser.add_argument("--radius", type=float, default=None, help="Optional radius in metres around coordinates.")
    parser.add_argument(
        "--offline-file",
        "--offline-geojson",
        dest="offline_file",
        default=None,
        help="Use a local OSM XML (.osm) or GeoJSON extract instead of downloading OSM data.",
    )
    parser.add_argument("--no-cache", action="store_false", dest="cache_downloads", help="Do not read or save successful downloads in cache/.")
    return parser.parse_args()


def main():
    args = parse_args()
    settings = default_settings()
    settings["cache_downloads"] = args.cache_downloads
    if args.offline_file:
        settings["offline_mode"] = True
        settings["offline_file_path"] = args.offline_file
    if args.gap_distance is not None:
        settings["gap_distance_m"] = args.gap_distance
    if args.top_n is not None:
        settings["top_n"] = args.top_n
    if args.lat is not None and args.lon is not None:
        settings["fallback_lat"] = args.lat
        settings["fallback_lon"] = args.lon
        settings["fallback_radius_m"] = args.radius or 1500
    elif args.radius is not None:
        settings["fallback_radius_m"] = args.radius

    print(f"Running analysis for: {args.area_name}")
    result = run_analysis(args.area_name, analyses=args.analyse, settings=settings)

    print("\nSelected analyses:", ", ".join(result["selected_analyses"]))
    for warning in result["warnings"]:
        print("Warning:", warning)

    summary_rows = []
    for name, df in result["results"].items():
        if df.empty:
            print(f"{name}: no gap results found.")
            continue
        top = df.head(min(5, len(df))).copy()
        print(f"\n{name} top results:")
        print(top[["rank", "place name", "place type", "score", "distance to nearest" if "distance to nearest" in top.columns else "distance to crossing"]].to_string(index=False))

    print("\nOutput files:")
    for label, path in result["output_files"].items():
        print(f"- {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
