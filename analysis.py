"""Main analysis runner for the road safety project."""

from __future__ import annotations

import pandas as pd

from analyses import base, crossings, railings, signs, speed_breakers
from config import ANALYSIS_CHOICES, DEFAULT_ANALYSES, default_settings


ANALYSIS_REGISTRY = {
    "crossings": crossings.analyse,
    "speed_breakers": speed_breakers.analyse,
    "signs": signs.analyse,
    "railings": railings.analyse,
}


def normalize_analyses(analyses=None):
    if analyses is None:
        analyses = DEFAULT_ANALYSES
    if isinstance(analyses, str):
        analyses = [part.strip() for part in analyses.split(",") if part.strip()]
    cleaned = []
    for name in analyses:
        name = str(name).strip().lower().replace("-", "_")
        if name in ANALYSIS_CHOICES and name not in cleaned:
            cleaned.append(name)
    if not cleaned:
        cleaned = DEFAULT_ANALYSES.copy()
    return cleaned


def run_analysis(area_name, analyses=None, settings=None, save_outputs=True):
    """Run selected analysis modules for an area and save output files."""
    settings = default_settings(settings or {})
    settings["area_name"] = area_name
    selected = normalize_analyses(analyses)

    base.DOWNLOAD_ERRORS.clear()
    results = {}
    warnings = []
    analysis_metadata = {}
    for name in selected:
        module_settings = default_settings(settings)
        try:
            df = ANALYSIS_REGISTRY[name](area_name, module_settings)
            results[name] = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
            analysis_metadata[name] = module_settings.get("analysis_metadata", {}).get(name, {
                "places_checked": 0,
                "mapped_feature_count": 0,
                "low_confidence": False,
            })
            mapped_count = int(analysis_metadata[name].get("mapped_feature_count", 0))
            places_checked = int(analysis_metadata[name].get("places_checked", 0))
            low_data = mapped_count < 15 or (
                places_checked > 0 and mapped_count / places_checked < 0.01
            )
            analysis_metadata[name]["low_data"] = low_data
            analysis_metadata[name]["low_confidence"] = (
                analysis_metadata[name].get("low_confidence", False) or low_data
            )
            if mapped_count == 0:
                feature_label = {
                    "crossings": "crossings",
                    "speed_breakers": "speed breakers",
                    "signs": "signs",
                    "railings": "railings or barriers",
                }[name]
                warnings.append(
                    f"No {feature_label} are mapped in this area, so this result is not reliable"
                )
            elif low_data:
                feature_label = {
                    "crossings": "crossings",
                    "speed_breakers": "speed breakers",
                    "signs": "signs",
                    "railings": "railings or barriers",
                }[name]
                warnings.append(
                    f"Only {mapped_count} {feature_label} are mapped in this area; "
                    "results are low confidence."
                )
            if analysis_metadata[name].get("low_confidence"):
                analysis_metadata[name]["confidence"] = "low confidence"
            else:
                analysis_metadata[name]["confidence"] = "normal"
        except Exception as exc:  # pragma: no cover - user-facing error reporting
            results[name] = pd.DataFrame()
            analysis_metadata[name] = {
                "places_checked": 0,
                "mapped_feature_count": 0,
                "low_confidence": True,
                "confidence": "low confidence",
                "error": str(exc),
            }
            warnings.append(f"{name}: {exc}")

    if base.DOWNLOAD_ERRORS:
        unique_errors = list(dict.fromkeys(base.DOWNLOAD_ERRORS))
        if settings.get("offline_mode"):
            warnings.append(
                "Offline mode could not use the selected map extract. Check that it is a valid OSM XML or "
                "GeoJSON file and covers the selected study area. Details: "
                + " | ".join(unique_errors[:3])
            )
        else:
            warnings.append(
                "OpenStreetMap place lookup can work while its separate Overpass data service is unavailable. "
                "Road/features could not be downloaded from the configured public Overpass instances, "
                "so these results are incomplete. Wait a few minutes and run the analysis again. "
                "Details: " + " | ".join(unique_errors[:3])
            )
    scoring_frames = []
    for name, df in results.items():
        if not df.empty:
            frame = df.copy()
            frame["_analysis_name"] = name
            frame["_source_index"] = range(len(frame))
            scoring_frames.append(frame)
    if scoring_frames:
        scored = base.score_results(pd.concat(scoring_frames, ignore_index=True))
        for name in selected:
            rows = scored.loc[scored["_analysis_name"] == name].copy()
            rows = rows.sort_values("score", ascending=False).reset_index(drop=True)
            rows["rank"] = range(1, len(rows) + 1)
            rows["confidence"] = analysis_metadata[name]["confidence"]
            results[name] = rows.drop(columns=["_analysis_name", "_source_index"])
    for name in selected:
        analysis_metadata[name]["gap_count"] = len(results[name])

    settings["analysis_metadata"] = analysis_metadata
    combined = base.combine_result_frames(results)
    file_paths = {}
    if save_outputs:
        output_dir = base.create_run_output_dir(area_name, selected)
        file_paths = base.save_project_outputs(area_name, results, combined, settings, output_dir)

    return {
        "area_name": area_name,
        "selected_analyses": selected,
        "results": results,
        "combined": combined,
        "warnings": warnings,
        "output_files": file_paths,
        "settings": settings,
    }
