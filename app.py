"""Streamlit application for the road safety analysis project."""

from __future__ import annotations

import html
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from analyses import base
from analysis import run_analysis
from config import ANALYSIS_CHOICES, default_settings


def _display_place_name(row):
    place_type = base.display_value(row.get("place type"), "place").replace("_", " ")
    name = base.display_value(row.get("place name"), f"Unnamed {place_type}")
    if name.lower() in {"unnamed", "unnamed place", "unknown"}:
        return f"Unnamed {place_type}"
    return name


st.set_page_config(
    layout="wide",
    page_title="RoadGap",
    initial_sidebar_state="expanded",
)
offline_fields_open = bool(st.session_state.get("offline_mode", False))
offline_fields_css = (
    """
    .st-key-offline-fields {
        max-height: 500px;
        opacity: 1;
        visibility: visible;
        pointer-events: auto;
        overflow: hidden;
        transition: max-height 420ms ease, opacity 260ms ease, visibility 0s;
    }
    """
    if offline_fields_open
    else """
    .st-key-offline-fields {
        max-height: 0;
        opacity: 0;
        visibility: hidden;
        pointer-events: none;
        overflow: hidden;
        transition: max-height 420ms ease, opacity 260ms ease, visibility 0s linear 420ms;
    }
    """
)
st.markdown(
    """
    <style>
    .block-container {padding-top: 1rem; padding-bottom: 1rem;}
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {padding-top: 0.5rem;}
    .stAlertContainer.st-emotion-cache-sbgf9b.ep9twe70 {margin-top: 50px;}
    .st-emotion-cache-1r1cntt.e15d17f11 {margin-top: -80px;}
    .st-emotion-cache-12bp31y.e1vmumty0 {z-index: 2147483647 !important;}
    .st-emotion-cache-l8irdn.epcrwu50 {border-bottom: 1px solid #44464d;}
    .stHorizontalBlock.st-emotion-cache-1a7w0so.e6x7pi3 {margin-top: 50px;}
    .stElementContainer.element-container.st-emotion-cache-zh2fnc.e6x7pi1 {margin-top: 0;}
    .st-emotion-cache-1fpp8sd {padding: 0 !important;}
    .st-emotion-cache-cm9vbh {padding: 0rem .75rem;border-radius: 0;}
    .st-emotion-cache-uofoxk {gap: 0.5rem;}
    .st-emotion-cache-zuyloh {border: none; padding:0;}
    .st-emotion-cache-1bnbo98 {gap: 0.5rem;}
    .st-emotion-cache-4bm6i2 {border-radius: 0;}
    .st-emotion-cache-13na8ym {border: none !important;}
    [data-baseweb="popover"] [role="option"] {padding-top: .35rem !important;padding-bottom: .35rem !important;min-height: 0 !important;}
    div[data-testid="stFormSubmitButton"] button {
        border: 1px solid #e76d56;
        border-radius: 8px;
        background: linear-gradient(135deg, #d94b37, #b9342d);
        color: #fff;
        font-weight: 650;
        box-shadow: 0 3px 0 #792821;
        transition: transform 160ms ease, box-shadow 160ms ease, filter 160ms ease;
    }
    div[data-testid="stFormSubmitButton"] button:hover:not(:disabled) {
        filter: brightness(1.12);
        transform: translateY(-2px);
        box-shadow: 0 5px 14px #d94b3766;
    }
    div[data-testid="stFormSubmitButton"] button:active:not(:disabled) {
        transform: translateY(1px);
        box-shadow: 0 1px 0 #792821;
    }
    div[data-testid="stFormSubmitButton"] button:focus-visible {
        outline: 3px solid #ffb49f;
        outline-offset: 3px;
    }
    """
    + offline_fields_css
    + """
    @media (prefers-reduced-motion: reduce) {
        div[data-testid="stFormSubmitButton"] button {transition: none;}
        .st-key-offline-fields {transition: none;}
    }
    h1 {font-size: 1.65rem !important; padding-bottom: 0 !important;}
    div[data-testid="stMetric"] {padding: .55rem .8rem; border: 1px solid #e6e9ef; border-radius: .6rem;}
    .st-key-top-gap-list .gap-card {padding:.65rem .8rem 0rem .8rem;}
    .gap-card-title {font-weight:650;font-size:1rem;margin-bottom:.2rem;}
    .gap-card-meta {font-size:.84rem;color:#596579;margin-bottom:.3rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

project_root = Path(__file__).resolve().parent
local_sources = ["Upload a local .osm or GeoJSON file"]
project_file_paths: dict[str, Path] = {}
for folder_name in ("OSM", "data"):
    folder_path = project_root / folder_name
    if folder_path.is_dir():
        for project_file in sorted(folder_path.iterdir()):
            if project_file.is_file() and project_file.suffix.lower() in {".osm", ".geojson", ".json"}:
                relative_path = project_file.relative_to(project_root).as_posix()
                label = f"Project file: {relative_path}"
                local_sources.append(label)
                project_file_paths[label] = project_file

with st.sidebar:
    st.title("RoadGap")
    st.caption("Find missing road safety features and design fixes")

    st.header("Analysis settings")
    offline_mode = st.checkbox(
        "Use local map data (offline)",
        value=st.session_state.get("offline_mode", False),
        key="offline_mode",
    )
    with st.form("analysis_form"):
        area_name = st.text_input("Place name or coordinates", value="Guindy, Chennai, India")
        local_source = None
        offline_file = None
        with st.container(key="offline-fields"):
            local_source = st.selectbox("Local map data", local_sources)
            offline_file = st.file_uploader(
                "Upload OSM XML or GeoJSON (optional when choosing a project file)",
                type=["osm", "geojson", "json"],
                help="Accepts an OSM XML .osm file, or a GeoJSON FeatureCollection. PBF files are not supported.",
            )
        selected_analyses = st.multiselect(
            "Analysis types",
            ANALYSIS_CHOICES,
            default=["crossings"],
            format_func=lambda value: value.replace("_", " ").title(),
        )
        gap_distance_m = st.slider("Gap distance (m)", min_value=50, max_value=200, value=100, step=5)
        top_n = st.slider("Top gaps to show", min_value=3, max_value=10, value=5, step=1)
        with st.expander("Advanced settings"):
            fallback_lat = st.text_input("Latitude (optional)", value="")
            fallback_lon = st.text_input("Longitude (optional)", value="")
            fallback_radius = st.number_input("Radius (m)", min_value=500, max_value=5000, value=1500, step=100)
            cache_downloads = st.checkbox(
                "Save downloads in cache/",
                value=True,
                help="Reuse successful data downloads on later runs.",
            )
        submitted = st.form_submit_button("Run analysis", use_container_width=True)

if submitted:
    if not area_name.strip():
        st.sidebar.error("Enter a place name or coordinates.")
    elif not selected_analyses:
        st.sidebar.error("Select at least one analysis type.")
    elif offline_mode and local_source == local_sources[0] and offline_file is None:
        st.sidebar.error("Choose or upload a local .osm or GeoJSON file.")
    else:
        try:
            settings = default_settings({
                "gap_distance_m": gap_distance_m,
                "top_n": top_n,
                "offline_mode": offline_mode,
                "cache_downloads": cache_downloads,
            })
            if offline_mode:
                settings["offline_mode"] = True
                if local_source in project_file_paths:
                    settings["offline_file_path"] = str(project_file_paths[local_source])
                else:
                    settings["offline_file_bytes"] = offline_file.getvalue()
                    settings["offline_file_name"] = offline_file.name
            if fallback_lat.strip() or fallback_lon.strip():
                if not fallback_lat.strip() or not fallback_lon.strip():
                    raise ValueError("Enter both latitude and longitude, or leave both blank.")
                settings["fallback_lat"] = float(fallback_lat)
                settings["fallback_lon"] = float(fallback_lon)
                settings["fallback_radius_m"] = int(fallback_radius)
            with st.spinner("Reading map file and finding gaps..."):
                result = run_analysis(area_name.strip(), analyses=selected_analyses, settings=settings)
            st.session_state["analysis_result"] = result
            st.session_state["analysis_run_id"] = (
                Path(result["output_files"].get("run_directory", "")).name
                or str(pd.Timestamp.now().value)
            )
        except (TypeError, ValueError) as exc:
            st.sidebar.error(str(exc))
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")


result = st.session_state.get("analysis_result")
if result is None:
    st.info("Choose a place and click Run analysis.")
    st.stop()

run_id = st.session_state.get("analysis_run_id", "current")
selected_names = result["selected_analyses"]
view_options = ["Combined"] + [name for name in selected_names]
if len(selected_names) > 1:
    chosen_view = st.radio(
        "Show results for",
        view_options,
        horizontal=True,
        format_func=lambda value: value.replace("_", " ").title(),
        key=f"analysis_view_{run_id}",
    )
else:
    chosen_view = selected_names[0]

metadata = result["settings"].get("analysis_metadata", {})
if chosen_view == "Combined":
    display_df = result["combined"].copy()
    view_metadata = {
        "places_checked": sum(int(item.get("places_checked", 0)) for item in metadata.values()),
        "mapped_feature_count": sum(int(item.get("mapped_feature_count", 0)) for item in metadata.values()),
    }
else:
    display_df = result["results"][chosen_view].copy()
    view_metadata = metadata.get(chosen_view, {})

display_df = display_df.copy()
if "rank" not in display_df:
    display_df["rank"] = range(1, len(display_df) + 1)
if "place name" in display_df:
    display_df["place name"] = display_df.apply(_display_place_name, axis=1)
top_gaps_df = display_df.head(int(result["settings"].get("top_n", 5)))

metric_cols = st.columns(3)
metric_cols[0].metric("Places checked", int(view_metadata.get("places_checked", 0)))
metric_cols[1].metric(
    "Gaps found",
    len(result["combined"]) if chosen_view == "Combined" else len(result["results"][chosen_view]),
)
metric_cols[2].metric("Mapped existing features", int(view_metadata.get("mapped_feature_count", 0)))

for warning in result.get("warnings", []):
    if "separate Overpass data service" in warning or "Offline mode could not" in warning:
        st.error(warning)

overview_tab, table_tab, charts_tab, report_tab, checklist_tab, downloads_tab = st.tabs(
    ["Overview", "Table", "Charts", "Report", "Street View checklist", "Downloads"]
)

with overview_tab:
    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.subheader("Map")
        if display_df.empty:
            focus_rank = st.selectbox("Focus on gap #", [0], format_func=lambda _: "No gaps available")
        else:
            rank_values = [int(value) for value in display_df["rank"].dropna().tolist()]
            focus_rank = st.selectbox(
                "Focus on gap #",
                [0] + rank_values,
                format_func=lambda value: "No focus" if value == 0 else f"#{value}",
                key=f"focus_{chosen_view}_{run_id}",
            )
        map_data_frames = []
        map_analysis_names = []
        names_for_map = selected_names if chosen_view == "Combined" else [chosen_view]
        if chosen_view == "Combined":
            if not display_df.empty:
                gap_map_rows = display_df.copy()
                gap_map_rows["analysis"] = "Combined"
                gap_map_rows["is_gap"] = True
                gap_map_rows["map_rank"] = gap_map_rows["rank"]
                map_data_frames.append(gap_map_rows)
            map_analysis_names = ["Combined"] + selected_names
        else:
            if not display_df.empty:
                gap_map_rows = display_df.copy()
                gap_map_rows["analysis"] = chosen_view
                gap_map_rows["is_gap"] = True
                gap_map_rows["map_rank"] = gap_map_rows["rank"]
                map_data_frames.append(gap_map_rows)
            map_analysis_names = [chosen_view]
        for analysis_name in names_for_map:
            existing = metadata.get(analysis_name, {}).get("existing_markers")
            if isinstance(existing, pd.DataFrame) and not existing.empty:
                map_data_frames.append(existing.assign(analysis=analysis_name, is_gap=False))
        roads = next(
            (
                item.get("map_roads")
                for name in names_for_map
                if (item := metadata.get(name, {})).get("map_roads") is not None
                and not item["map_roads"].empty
            ),
            None,
        )
        map_rows = pd.concat(map_data_frames, ignore_index=True) if map_data_frames else pd.DataFrame()
        if not map_rows.empty:
            map_center_lat = float(pd.to_numeric(map_rows["lat"], errors="coerce").mean())
            map_center_lon = float(pd.to_numeric(map_rows["lon"], errors="coerce").mean())
        elif roads is not None and not roads.empty:
            center = roads.to_crs("EPSG:4326").geometry.union_all().centroid
            map_center_lat, map_center_lon = float(center.y), float(center.x)
        else:
            map_center_lat, map_center_lon = 13.0, 80.2
        focus_lat = None
        focus_lon = None
        if focus_rank:
            focused_rows = display_df.loc[
                pd.to_numeric(display_df["rank"], errors="coerce") == int(focus_rank)
            ]
            if not focused_rows.empty:
                focus_lat = float(focused_rows.iloc[0]["lat"])
                focus_lon = float(focused_rows.iloc[0]["lon"])
                map_center_lat, map_center_lon = focus_lat, focus_lon
        map_obj = base.make_gap_map(
            map_rows,
            map_center_lat,
            map_center_lon,
            roads,
            analysis_names=map_analysis_names,
        )
        map_html = map_obj.get_root().render()
        if focus_rank and focus_lat is not None and focus_lon is not None:
            map_match = re.search(r"var (map_[A-Za-z0-9_]+) = L\.map", map_html)
            if map_match:
                focus_script = f"""
                <script>
                (function() {{
                  const targetMap = {map_match.group(1)};
                  const targetRank = {int(focus_rank)};
                  const targetLat = {focus_lat:.12f};
                  const targetLon = {focus_lon:.12f};
                  targetMap.setView([targetLat, targetLon], 17);
                  let found = false;
                  function visit(layer) {{
                    if (found) return;
                    if (layer.getPopup && layer.getLatLng && layer.getPopup()) {{
                      const content = layer.getPopup().getContent();
                      const text = typeof content === "string"
                        ? content
                        : content && typeof content.text === "function"
                          ? content.text()
                          : content && content.textContent || "";
                      if (text.includes("#" + targetRank + " ")) {{
                        targetMap.setView(layer.getLatLng(), 17);
                        layer.openPopup();
                        found = true;
                      }}
                    }}
                    if (layer.eachLayer) layer.eachLayer(visit);
                  }}
                  targetMap.eachLayer(visit);
                }})();
                </script>
                """
                map_html = map_html.replace("</body>", focus_script + "</body>")
        st.components.v1.html(map_html, height=520, scrolling=False)

    with right:
        st.subheader("Top gaps")
        with st.container(height=605, border=False, key="top-gap-list"):
            if display_df.empty:
                st.info("No reliable gap rows are available for this view.")
            else:
                for _, row in top_gaps_df.iterrows():
                    rank = int(row.get("rank", 0))
                    name = _display_place_name(row)
                    place_type = base.display_value(row.get("place type"), "Unknown")
                    distance_value = base.display_value(
                        row.get("distance to nearest", row.get("distance to crossing")),
                        "Not mapped",
                    )
                    distance_text = (
                        f"{distance_value} m" if distance_value != "Not mapped" else distance_value
                    )
                    score_value = pd.to_numeric(row.get("score"), errors="coerce")
                    confidence = base.display_value(row.get("confidence"), "normal")
                    confidence_color = "#9a6700" if confidence == "low confidence" else "#116329"
                    score_text = f"{score_value:.1f}" if pd.notna(score_value) else "N/A"
                    with st.container(border=True):
                        st.markdown(
                            f'<div class="gap-card"><div class="gap-card-title">#{rank} {html.escape(name)}</div>'
                            f'<div class="gap-card-meta">{html.escape(place_type)} · {html.escape(distance_text)}'
                            f' · Score {score_text}'
                            f' · <span style="color:{confidence_color};font-weight:600">{html.escape(confidence)}</span></div></div>',
                            unsafe_allow_html=True,
                        )
                        with st.expander("Details", key=f"details_{chosen_view}_{rank}_{run_id}"):
                            st.write(f"**Why it is risky:** {base.display_value(row.get('reason'), 'Risk factors need checking.')}")
                            st.write(f"**Suggested fix:** {base.display_value(row.get('suggested fix'), 'Review the site.')}")
                            road_note = base.display_value(row.get("road note"), "")
                            if road_note:
                                st.write(f"**Road note:** {road_note}")
                            street_view = base.display_value(row.get("street view link"), "")
                            if street_view:
                                st.link_button("Open Street View", street_view, width="stretch")

with table_tab:
    show_all_columns = st.toggle("Show all columns", key=f"show_all_{chosen_view}_{run_id}")
    if display_df.empty:
        st.info("No results to display.")
    elif show_all_columns:
        st.dataframe(display_df, width="stretch", hide_index=True)
    else:
        distance_column = (
            "distance to nearest"
            if "distance to nearest" in display_df.columns
            else "distance to crossing"
        )
        columns = ["rank", "place name", "place type", "road name", distance_column, "score", "confidence"]
        visible_columns = list(dict.fromkeys(column for column in columns if column in display_df.columns))
        st.dataframe(display_df[visible_columns], width="stretch", hide_index=True)

with charts_tab:
    chart_left, chart_right = st.columns(2)
    chart_data = display_df.head(10).copy()
    with chart_left:
        st.caption("Top gap scores")
        if chart_data.empty:
            st.info("No chart data.")
        else:
            chart_data = chart_data.iloc[::-1]
            labels = [
                f"#{int(row['rank'])} {base._short_chart_name(_display_place_name(row))}"
                for _, row in chart_data.iterrows()
            ]
            fig, ax = plt.subplots(figsize=(5.5, 3.2))
            ax.barh(labels, pd.to_numeric(chart_data["score"], errors="coerce"), color="#d73027")
            ax.set_xlabel("Score (20-100)")
            fig.tight_layout()
            st.pyplot(fig, width="stretch")
            plt.close(fig)
    with chart_right:
        if chosen_view == "Combined" and len(selected_names) > 1:
            st.caption("Gap types per combined place")
            counts = chart_data.groupby("rank")["gap type count"].max().sort_values()
            labels = [
                f"#{int(rank)} {base._short_chart_name(chart_data.loc[chart_data['rank'] == rank, 'place name'].iloc[0])}"
                for rank in counts.index
            ]
        else:
            st.caption("Gap counts by place type")
            counts = display_df.groupby("place type").size().sort_values() if "place type" in display_df else pd.Series(dtype=int)
            if chosen_view == "railings" or (chosen_view == "Combined" and selected_names == ["railings"]):
                counts = counts.drop(index="crossing", errors="ignore")
            labels = [base._short_chart_name(value) for value in counts.index]
        if counts.empty:
            st.info("No chart data.")
        else:
            fig, ax = plt.subplots(figsize=(5.5, 3.2))
            ax.barh(labels, counts.values, color="#1f77b4")
            ax.set_xlabel(
                "Number of gap types"
                if chosen_view == "Combined" and len(selected_names) > 1
                else "Number of places"
            )
            fig.tight_layout()
            st.pyplot(fig, width="stretch")
            plt.close(fig)

with report_tab:
    report_lines = [
        f"### Summary for {result['area_name']}",
        f"- Places checked: {int(view_metadata.get('places_checked', 0))}",
        f"- Gaps found: {len(result['combined']) if chosen_view == 'Combined' else len(result['results'][chosen_view])}",
        f"- Mapped existing features: {int(view_metadata.get('mapped_feature_count', 0))}",
        "",
    ]
    st.markdown("\n".join(report_lines))
    if display_df.empty:
        st.info("No reliable gap details are available.")
    else:
        for _, row in display_df.iterrows():
            rank = int(row.get("rank", 0))
            name = _display_place_name(row)
            with st.expander(f"#{rank} {name}"):
                if chosen_view == "Combined" and len(selected_names) > 1:
                    st.write(
                        f"**Gap types:** {base.display_value(row.get('gap types'), 'Unknown')} "
                        f"({int(row.get('gap type count', 1))})"
                    )
                st.write(f"**Why it is risky:** {base.display_value(row.get('reason'), 'Risk factors need checking.')}")
                st.write(f"**Suggested fix:** {base.display_value(row.get('suggested fix'), 'Review the site.')}")
                road_note = base.display_value(row.get("road note"), "")
                if road_note:
                    st.write(f"**Road note:** {road_note}")
                link = base.display_value(row.get("street view link"), "")
                if link:
                    st.markdown(f"[Open Street View]({link})")

checklist_base = top_gaps_df
checklist_key = f"checklist_editor_{chosen_view}_{run_id}"
with checklist_tab:
    checklist = pd.DataFrame({
        "rank": checklist_base.get("rank", pd.Series(dtype=int)).astype(int).tolist(),
        "place name": checklist_base.get("place name", pd.Series(dtype=str)).astype(str).tolist(),
        "Street View link": checklist_base.get("street view link", pd.Series(dtype=str)).astype(str).tolist(),
        "Gap confirmed?": ["" for _ in range(len(checklist_base))],
        "Notes": ["" for _ in range(len(checklist_base))],
    })
    edited_checklist = st.data_editor(
        checklist,
        width="stretch",
        hide_index=True,
        key=checklist_key,
        column_config={
            "rank": st.column_config.NumberColumn("Rank", disabled=True, width="small"),
            "place name": st.column_config.TextColumn("Place name", disabled=True),
            "Street View link": st.column_config.LinkColumn(
                "Street View link",
                display_text="Open Street View",
                disabled=True,
            ),
            "Gap confirmed?": st.column_config.SelectboxColumn(
                "Gap confirmed?",
                options=["yes", "no", "partly"],
                required=False,
            ),
            "Notes": st.column_config.TextColumn("Notes"),
        },
    )
    checklist_csv = edited_checklist.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download checklist CSV",
        checklist_csv,
        file_name="street_view_checklist.csv",
        mime="text/csv",
        key=f"checklist_download_{chosen_view}_{run_id}",
    )

with downloads_tab:
    files = result.get("output_files", {})
    run_directory = files.get("run_directory")
    if run_directory:
        st.caption(f"This run's files are saved in: {run_directory}")
    download_columns = st.columns(4)

    def download_file(column, label, file_key, fallback_name, fallback_frame=None):
        file_path = files.get(file_key)
        if file_path and Path(file_path).is_file():
            payload = Path(file_path).read_bytes()
        elif fallback_frame is not None:
            payload = fallback_frame.to_csv(index=False).encode("utf-8")
        else:
            return
        column.download_button(
            label,
            payload,
            file_name=Path(file_path).name if file_path else fallback_name,
            mime="text/csv" if fallback_name.endswith(".csv") else "text/markdown",
            width="stretch",
            key=f"download_{file_key}_{chosen_view}_{run_id}",
        )

    download_file(
        download_columns[0],
        "Analysis CSV",
        f"{chosen_view}_csv" if chosen_view != "Combined" else f"{selected_names[0]}_csv",
        f"{chosen_view}.csv",
        result["results"].get(chosen_view) if chosen_view != "Combined" else result["combined"],
    )
    download_file(
        download_columns[1],
        "Combined CSV",
        "top_gaps_csv",
        "top_gaps.csv",
        result["combined"],
    )
    download_file(
        download_columns[2],
        "Summary report",
        "summary_report",
        "top_gaps_summary.md",
    )
    download_columns[3].download_button(
        "Checklist CSV",
        edited_checklist.to_csv(index=False).encode("utf-8"),
        file_name="street_view_checklist.csv",
        mime="text/csv",
        width="stretch",
        key=f"checklist_downloads_{chosen_view}_{run_id}",
    )
