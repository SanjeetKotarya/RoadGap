"""Streamlit application for the road safety analysis project."""

from __future__ import annotations

import base64
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
ui_folder = Path(__file__).resolve().parent / "UI"
sidebar_background = base64.b64encode((ui_folder / "sidebar.jpg").read_bytes()).decode("ascii")
main_background = base64.b64encode((ui_folder / "rightside.jpg").read_bytes()).decode("ascii")
map_pin_icon = base64.b64encode((ui_folder / "pin.png").read_bytes()).decode("ascii")
places_card_background = base64.b64encode((ui_folder / "places.jpg").read_bytes()).decode("ascii")
stack_icon = base64.b64encode((ui_folder / "stack.png").read_bytes()).decode("ascii")
mapped_card_background = base64.b64encode((ui_folder / "mapped.jpg").read_bytes()).decode("ascii")
gaps_card_background = base64.b64encode((ui_folder / "gaps.jpg").read_bytes()).decode("ascii")
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
    (
    """
    <style>
    html, body {
        background: linear-gradient(180deg, #070d1c 0%, #0a1327 30%, #090f21 100%);
        color: #f4f5ff;
    }
    .stApp {
        background-image:
            linear-gradient(rgba(7, 11, 21, 0.48), rgba(7, 11, 21, 0.58)),
            url("__MAIN_BACKGROUND__");
        background-position: center center;
        background-size: cover;
        background-repeat: no-repeat;
        background-attachment: fixed;
    }
    [data-testid="stAppViewContainer"] {
        background: transparent;
    }
    .st-emotion-cache-99p1qr {
        background: transparent !important;
    }
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        max-width: 100% !important;
    }
    [data-testid="stMain"] .block-container {
        padding-top: 50px !important;
    }
    [data-testid="stSidebar"] {
        background-image:
            linear-gradient(rgba(9, 13, 22, 0.70), rgba(9, 13, 22, 0.48)),
            url("__SIDEBAR_BACKGROUND__");
        background-position: center center;
        background-size: cover;
        background-repeat: no-repeat;
        border-right: 1px solid rgba(135, 150, 190, 0.15);
        box-shadow: inset -1px 0 0 rgba(255,255,255,0.02);
    }
    [data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
        height: 0 !important;
        min-height: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding: 0 1rem 1rem 1rem;
    }
    [data-testid="stSidebar"] .st-emotion-cache-1r1cntt {
        padding-bottom: 0 !important;
    }
    [data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] {
        position: relative;
        top: 2.75rem;
        z-index: 20;
    }
    [data-testid="stSidebar"] .st-key-sidebar-brand {
        padding-right: 2.5rem;
    }
    [data-testid="stSidebar"] .st-key-sidebar-brand h1 {
        margin-top: 0 !important;
    }
    [data-testid="stSidebar"] .st-key-sidebar-brand [data-testid="stCaptionContainer"] {
        margin-top: 0.35rem;
    }
    [data-testid="stSidebar"] .st-key-sidebar-brand {
        padding-bottom: 1rem;
        margin-bottom: 1rem;
        border-bottom: 1px solid rgba(164, 178, 210, 0.2);
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] .stMarkdown {
        color: #eef4ff !important;
    }
    [data-testid="stSidebar"] .stCheckbox,
    [data-testid="stSidebar"] .stSelectbox,
    [data-testid="stSidebar"] .stTextInput,
    [data-testid="stSidebar"] .stNumberInput,
    [data-testid="stSidebar"] .stFileUploader,
    [data-testid="stSidebar"] .stMultiSelect,
    [data-testid="stSidebar"] .stSlider,
    [data-testid="stSidebar"] .stRadio,
    [data-testid="stSidebar"] .stForm {
        width: 100%;
    }
    [data-testid="stSidebar"] .stTextInput input,
    [data-testid="stSidebar"] .stNumberInput input,
    [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div,
    [data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] > div,
    [data-testid="stSidebar"] .stFileUploader > div,
    [data-testid="stSidebar"] .stSlider [data-testid="stBaseSlider"] {
        background: rgba(19, 28, 41, 0.92) !important;
        border: 1px solid rgba(145, 170, 220, 0.2);
        border-radius: 12px;
        color: #eaf2ff;
    }
    [data-testid="stSidebar"] .stFileUploader button,
    [data-testid="stSidebar"] .stButton > button,
    div[data-testid="stFormSubmitButton"] button {
        border-radius: 12px !important;
        border: 1px solid rgba(255, 118, 92, 0.8) !important;
        background: linear-gradient(135deg, #ef5d4d 0%, #cf2f3c 100%) !important;
        color: #fff !important;
        font-weight: 700 !important;
        letter-spacing: 0.01em;
        box-shadow: 0 8px 20px rgba(211, 68, 59, 0.25);
    }
    [data-testid="stSidebar"] .stButton > button:hover,
    div[data-testid="stFormSubmitButton"] button:hover:not(:disabled) {
        filter: brightness(1.08);
        transform: translateY(-1px);
        box-shadow: 0 12px 26px rgba(211, 68, 59, 0.32);
    }
    [data-testid="stSidebar"] .stSlider [data-testid="stBaseSlider"] {
        padding: 0 0.2rem;
    }
    [data-testid="stSidebar"] .stSlider [data-testid="stBaseSlider"] > div {
        background: linear-gradient(90deg, #ef5d4d, #8e3de5) !important;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.02);
        color: #eef6ff;
    }
    [data-testid="stSidebar"] .stExpander {
        border: none !important;
        background: transparent;
    }
    [data-testid="stSidebar"] .stExpander summary {
        background: rgba(255,255,255,0.02);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 10px;
        color: #f0f4ff !important;
    }
    [data-testid="stSidebar"] .stExpander summary:hover {
        border-color: rgba(255,255,255,0.12);
    }
    [data-testid="stSidebar"] .stAlert,
    [data-testid="stSidebar"] .stError,
    [data-testid="stSidebar"] .stWarning,
    [data-testid="stSidebar"] .stSuccess {
        border-radius: 12px;
        margin-top: 0.65rem;
    }
    [data-testid="stSidebar"] .stMarkdown h3 {
        margin-top: 0.8rem;
        font-size: 1rem;
        font-weight: 600;
        color: #eff5ff !important;
    }
    [data-testid="stSidebar"] .st-key-analysis-settings-heading h2 {
        display: flex;
        align-items: center;
        gap: 0.55rem;
        font-size: 1rem !important;
    }
    [data-testid="stSidebar"] .st-key-analysis-settings-heading h2::before {
        content: "tune";
        font-family: "Material Symbols Rounded";
        font-size: 1.15rem;
        line-height: 1;
        font-weight: 400;
        font-feature-settings: "liga";
        color: #dce5f6;
    }
    .stTabs [role="tablist"],
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.55rem;
        margin-top: 0.25rem;
        margin-bottom: 1rem;
        border: 0 !important;
        border-bottom: 0 !important;
        box-shadow: none !important;
        background: transparent;
    }
    .stTabs [role="tablist"]::before,
    .stTabs [role="tablist"]::after,
    .stTabs .react-aria-SelectionIndicator,
    .stTabs [role="tab"]::after,
    .stTabs [role="tab"][aria-selected="true"]::after,
    .stTabs [role="tablist"] > :not([role="tab"]),
    .stTabs [data-baseweb="tab-border"],
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-highlight"] *,
    .stTabs [data-baseweb="tab-list"]::before,
    .stTabs [data-baseweb="tab-list"]::after {
        display: none !important;
        content: none !important;
        height: 0 !important;
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    .stTabs [role="tab"] {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        background: rgba(21, 25, 40, 0.88);
        border: 1px solid rgba(140, 151, 185, 0.08);
        border-radius: 999px;
        color: #c6ccdc;
        padding: 0.45rem 1rem;
        font-weight: 600;
        min-height: 2.7rem;
        border-bottom: 0 !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.025);
        transition: background 160ms ease, border-color 160ms ease, color 160ms ease, box-shadow 160ms ease;
    }
    .stTabs [role="tab"]::before {
        display: inline-block;
        color: #cbd2e2;
        font-family: "Segoe UI Symbol", sans-serif;
        font-size: 1.05rem;
        line-height: 1;
    }
    .stTabs [role="tab"]:nth-of-type(1)::before { content: "⊞"; }
    .stTabs [role="tab"]:nth-of-type(2)::before { content: "▤"; }
    .stTabs [role="tab"]:nth-of-type(3)::before { content: "↗"; }
    .stTabs [role="tab"]:nth-of-type(4)::before { content: "▣"; }
    .stTabs [role="tab"]:nth-of-type(5)::before { content: "♧"; }
    .stTabs [role="tab"]:nth-of-type(6)::before { content: "⇩"; }
    .stTabs [role="tab"]:hover {
        background: rgba(30, 35, 54, 0.96);
        border-color: rgba(177, 186, 212, 0.2);
        color: #f3f5fb;
    }
    .stTabs [role="tab"][aria-selected="true"] {
        background: linear-gradient(180deg, #ed424c, #c82c3d);
        border-color: #fa5960;
        border-bottom: 0 !important;
        color: #fff;
        box-shadow: none !important;
        filter: none !important;
        text-decoration: none !important;
    }
    .stTabs [role="tab"][aria-selected="true"]::before {
        color: #fff;
    }
    .st-key-places-metric-card [data-testid="stMetric"],
    .st-key-gaps-metric-card [data-testid="stMetric"],
    .st-key-mapped-metric-card [data-testid="stMetric"] {
        position: relative;
        display: flex;
        align-items: center;
        overflow: hidden;
        border: 1px solid rgba(150, 164, 204, 0.16);
        border-radius: 20px;
        padding: 0.8rem 1rem 0.8rem 6.1rem;
        box-shadow: 0 10px 24px rgba(2, 6, 17, 0.27), inset 0 1px 0 rgba(255,255,255,0.035);
    }
    .st-key-places-metric-card [data-testid="stMetric"] {
        background-image:
            linear-gradient(120deg, rgba(33, 24, 42, 0.6), rgba(17, 22, 38, 0.5) 56%, rgba(52, 26, 42, 0.38)),
            url("__PLACES_CARD_BACKGROUND__");
        background-position: center, right center;
        background-size: cover, cover;
        background-repeat: no-repeat;
        border-color: rgba(246, 94, 99, 0.22);
    }
    .st-key-gaps-metric-card [data-testid="stMetric"] {
        background-image:
            linear-gradient(120deg, rgba(31, 25, 53, 0.58), rgba(17, 22, 39, 0.48) 58%, rgba(49, 28, 77, 0.35)),
            url("__GAPS_CARD_BACKGROUND__");
        background-position: center, right center;
        background-size: cover, cover;
        background-repeat: no-repeat;
        border-color: rgba(143, 75, 245, 0.22);
    }
    .st-key-mapped-metric-card [data-testid="stMetric"] {
        background-image:
            linear-gradient(120deg, rgba(20, 38, 43, 0.58), rgba(17, 24, 39, 0.48) 58%, rgba(18, 56, 49, 0.35)),
            url("__MAPPED_CARD_BACKGROUND__");
        background-position: center, right center;
        background-size: cover, cover;
        background-repeat: no-repeat;
        border-color: rgba(36, 210, 136, 0.2);
    }
    .st-key-places-metric-card [data-testid="stMetric"]::before,
    .st-key-gaps-metric-card [data-testid="stMetric"]::before,
    .st-key-mapped-metric-card [data-testid="stMetric"]::before {
        position: absolute;
        left: 1rem;
        top: 50%;
        display: grid;
        width: 4.2rem;
        height: 4.2rem;
        place-items: center;
        border-radius: 50%;
        transform: translateY(-50%);
        font-size: 2.1rem;
        line-height: 1;
    }
    .st-key-places-metric-card [data-testid="stMetric"]::before {
        content: "";
        background-image:
            linear-gradient(270deg, rgba(255, 75, 81, 0.34) 0%, rgba(190, 48, 69, 0.19) 100%),
            url("__MAP_PIN_ICON__");
        background-position: center, center;
        background-repeat: no-repeat;
        background-size: cover, 2rem 2rem;
        box-shadow: 0 0 0 1px rgba(255, 89, 95, 0.08), 0 0 28px rgba(255, 66, 75, 0.13);
    }
    .st-key-gaps-metric-card [data-testid="stMetric"]::before {
        content: "!";

        background: linear-gradient(270deg, rgba(168, 85, 247, 0.54) 0%, rgba(124, 58, 237, 0.19) 100%);
        color: #fff;
        font-family: Arial, sans-serif;
        font-weight: 700;
        box-shadow: 0 0 27px rgba(133, 63, 235, 0.18);
    }
    .st-key-mapped-metric-card [data-testid="stMetric"]::before {
        content: "";
        background-image:
            linear-gradient(270deg, rgba(30, 217, 139, 0.3), rgba(23, 144, 105, 0.18)),
            url("__STACK_ICON__");
        background-position: center, center;
        background-repeat: no-repeat;
        background-size: cover, 2.5rem 2.5rem;
        box-shadow: 0 0 0 1px rgba(54, 218, 147, 0.08), 0 0 28px rgba(32, 217, 140, 0.13);
    }
    .st-emotion-cache-1bnbo98:has(iframe),
    .st-emotion-cache-1bnbo98:has(.st-key-top-gap-list) {
        box-sizing: border-box;
        overflow: hidden;
        padding: 0.65rem 0.7rem 0.75rem;
        border: 1px solid rgba(133, 146, 182, 0.2) !important;
        border-radius: 22px !important;
        background: linear-gradient(145deg, rgba(18, 23, 39, 0.94), rgba(12, 17, 30, 0.97)) !important;
        box-shadow: 0 12px 30px rgba(2, 6, 17, 0.3), inset 0 1px 0 rgba(255,255,255,0.035);
    }
    [data-testid="column"]:has(iframe) h2,
    [data-testid="column"]:has(.st-key-top-gap-list) h2 {
        margin-top: 0.15rem !important;
        margin-bottom: 0.6rem !important;
    }
    .map-panel-title {
        display: flex;
        align-items: center;
        gap: 0.55rem;
        margin: 0.15rem 0 0.6rem;
        color: #f1f5ff;
        font-size: 1.3rem;
        font-weight: 700;
        line-height: 1.35;
    }
    .map-panel-title::before {
        content: "";
        flex: 0 0 1.15rem;
        width: 1.15rem;
        height: 1.35rem;
        background: center / contain no-repeat url("__MAP_PIN_ICON__");
        filter: drop-shadow(0 0 5px rgba(248, 66, 91, 0.24));
    }
    [data-testid="column"]:has(iframe) iframe {
        border-radius: 14px;
    }
    .focus-gap-label {
        display: flex;
        align-items: center;
        min-height: 2.7rem;
        color: #dce3f2;
        font-size: 0.95rem;
        font-weight: 550;
        white-space: nowrap;
    }
    [data-testid="column"]:has(iframe) [data-testid="stSelectbox"] {
        padding-top: 0 !important;
        margin-top: 0 !important;
    }
    [data-testid="column"]:has(iframe) [data-testid="stSelectbox"] > label {
        display: none;
    }
    [data-testid="column"]:has(iframe) [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        min-height: 2.7rem;
        border: 1px solid rgba(146, 158, 194, 0.12) !important;
        border-radius: 14px !important;
        background: rgba(27, 31, 49, 0.9) !important;
    }
    [data-testid="stMetric"] > div {
        font-size: 0.9rem;
        color: #dfe8ff;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.82rem !important;
        letter-spacing: 0.01em;
        color: #d5daea !important;
    }
    [data-testid="stMetricValue"] {
        font-size: clamp(1.8rem, 2.2vw, 2.45rem) !important;
        font-weight: 750 !important;
        color: #f7f8ff !important;
        line-height: 1.15;
    }
    [data-testid="stMetricDelta"] {
        color: #20d879 !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stDecorativeBlock"],
    [data-testid="stContainer"] {
        background: transparent;
    }
    [data-testid="stFormSubmitButton"] button {
        width: 100%;
        min-height: 2.9rem;
    }
    .st-key-top-gap-heading {
        margin: 0 0 0.35rem;
    }
    .st-key-top-gap-heading p {
        display: flex;
        align-items: center;
        gap: 0.55rem;
        margin: 0;
        color: #f4f5ff;
        font-size: 1.3rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .st-key-top-gap-heading p::before {
        content: "💡";
        font-size: 1.35rem;
        filter: drop-shadow(0 0 7px rgba(255, 195, 59, 0.38));
    }
    .st-key-top-gap-list [data-testid="stVerticalBlockBorderWrapper"]:has(.gap-card) {
        overflow: hidden;
        border: 1px solid rgba(151, 164, 201, 0.22) !important;
        border-radius: 16px !important;
        background: linear-gradient(145deg, rgba(20, 25, 41, 0.96), rgba(13, 18, 31, 0.96));
        box-shadow: 0 8px 22px rgba(3, 6, 15, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.035);
        padding: 0.6rem 0.75rem 0.45rem;
        transition: border-color 160ms ease, box-shadow 160ms ease;
    }
    .st-key-top-gap-list > div[data-testid="stVerticalBlock"] {
        gap: 0.65rem !important;
    }
    .st-key-top-gap-list [data-testid="stVerticalBlockBorderWrapper"]:has(.gap-card):hover {
        border-color: rgba(179, 190, 224, 0.34) !important;
        box-shadow: 0 10px 24px rgba(3, 6, 15, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.045);
    }
    .st-key-top-gap-list .gap-card {
        padding: 0 0.05rem 0.25rem;
    }
    .st-key-top-gap-list .gap-card-title {
        font-weight: 700;
        font-size: 1.02rem;
        line-height: 1.35;
        margin-bottom: 0.28rem;
        color: #f2f4fb;
    }
    .st-key-top-gap-list .gap-card-meta {
        font-size: 0.84rem;
        line-height: 1.5;
        color: #aeb8d0;
    }
    .st-key-top-gap-list .gap-confidence {
        display: inline-block;
        color: #ffc43d;
        font-weight: 650;
        white-space: nowrap;
    }
    .st-key-top-gap-list [data-testid="stExpander"] {
        overflow: hidden;
        border: 0 !important;
        border-radius: 0 0 10px 10px;
        background: transparent;
        box-sizing: border-box;
        width: calc(100% + 1.5rem) !important;
        max-width: none !important;
        margin: 0 -0.75rem 0.1rem;
    }
    .st-key-top-gap-list [data-testid="stExpander"] summary {
        display: flex;
        align-items: center;
        min-height: 2.45rem;
        padding: 0.35rem 0.9rem;
        background: rgba(113, 125, 157, 0.13);
        color: #e5e9f4 !important;
        font-weight: 550;
        transition: background 160ms ease;
    }
    .st-key-top-gap-list [data-testid="stExpander"] summary > div {
        display: flex;
        align-items: center;
    }
    .st-key-top-gap-list [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p {
        margin: 0 !important;
        line-height: 1.25;
    }
    .st-key-top-gap-list [data-testid="stExpander"] summary svg {
        display: block;
        flex: 0 0 auto;
    }
    .st-key-top-gap-list [data-testid="stExpander"] summary:hover,
    .st-key-top-gap-list [data-testid="stExpander"] details[open] > summary {
        background: rgba(123, 136, 170, 0.2);
    }
    .st-key-top-gap-list [data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {
        color: #d7dceb;
        font-size: 0.91rem;
        line-height: 1.58;
        margin-bottom: 0.85rem;
    }
    .st-key-top-gap-list [data-testid="stExpander"] [data-testid="stMarkdownContainer"] strong {
        color: #f1f3fa;
        font-weight: 700;
    }
    .st-key-top-gap-list [data-testid="stLinkButton"] a {
        min-height: 2.7rem;
        border: 1px solid rgba(146, 158, 194, 0.12) !important;
        border-radius: 12px !important;
        background: rgba(91, 103, 134, 0.2) !important;
        color: #e8ebf5 !important;
        font-weight: 600 !important;
        box-shadow: none !important;
        transition: background 160ms ease, border-color 160ms ease;
    }
    .st-key-top-gap-list [data-testid="stLinkButton"] a:hover {
        background: rgba(108, 121, 154, 0.3) !important;
        border-color: rgba(176, 187, 220, 0.28) !important;
    }
    .stMarkdown h2 {
        color: #f1f5ff !important;
        font-size: 1.3rem !important;
        margin-bottom: 0.7rem !important;
    }
    .stDataFrame {
        background: rgba(15, 22, 34, 0.8);
        border: 1px solid rgba(158, 172, 214, 0.12);
        border-radius: 15px;
    }
    .stDataFrame > div {
        border-radius: 15px;
    }
    .stCheckbox > label,
    .stRadio > label,
    .stSelectbox > label,
    .stTextInput > label,
    .stNumberInput > label,
    .stFileUploader > label,
    .stMultiSelect > label,
    .stSlider > label {
        font-weight: 600;
        color: #edf3ff !important;
    }
    .stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {
        background: rgba(12, 18, 28, 0.9) !important;
        color: #f0f6ff !important;
    }
    .stTextInput input::placeholder {
        color: rgba(175, 193, 221, 0.72);
    }
    .stSelectbox [data-baseweb="popover"] {
        background: rgba(13, 20, 31, 0.98);
        border: 1px solid rgba(164, 180, 220, 0.2);
    }
    [data-baseweb="popover"] [role="option"] {
        color: #edf3ff !important;
        background: rgba(13, 20, 31, 0.98);
        padding-top: 0.35rem !important;
        padding-bottom: 0.35rem !important;
        min-height: 0 !important;
    }
    [data-baseweb="popover"] [role="option"][aria-selected="true"] {
        background: rgba(255, 111, 87, 0.18);
    }
    .st-key-offline-fields {
        transition: max-height 420ms ease, opacity 260ms ease, visibility 0s;
    }
    .st-emotion-cache-q25c8l {
        gap: 0 !important;
    }
    """
    + offline_fields_css
    + """
    @media (prefers-reduced-motion: reduce) {
        div[data-testid="stFormSubmitButton"] button {transition: none;}
        .st-key-offline-fields {transition: none;}
    }
    </style>
    """
    )
    .replace("__MAIN_BACKGROUND__", f"data:image/jpeg;base64,{main_background}")
    .replace("__SIDEBAR_BACKGROUND__", f"data:image/jpeg;base64,{sidebar_background}")
    .replace("__MAP_PIN_ICON__", f"data:image/png;base64,{map_pin_icon}")
    .replace("__PLACES_CARD_BACKGROUND__", f"data:image/jpeg;base64,{places_card_background}")
    .replace("__STACK_ICON__", f"data:image/png;base64,{stack_icon}")
    .replace("__MAPPED_CARD_BACKGROUND__", f"data:image/jpeg;base64,{mapped_card_background}")
    .replace("__GAPS_CARD_BACKGROUND__", f"data:image/jpeg;base64,{gaps_card_background}"),
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
    with st.container(key="sidebar-brand"):
        st.title("RoadGap")
        st.caption("Find missing road safety features and design fixes")

    with st.container(key="analysis-settings-heading"):
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
                "Upload OSM XML or GeoJSON",
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
with metric_cols[0]:
    with st.container(key="places-metric-card"):
        st.metric("Places checked", int(view_metadata.get("places_checked", 0)))
with metric_cols[1]:
    with st.container(key="gaps-metric-card"):
        st.metric(
            "Gaps found",
            len(result["combined"]) if chosen_view == "Combined" else len(result["results"][chosen_view]),
        )
with metric_cols[2]:
    with st.container(key="mapped-metric-card"):
        st.metric("Mapped existing features", int(view_metadata.get("mapped_feature_count", 0)))

for warning in result.get("warnings", []):
    if "separate Overpass data service" in warning or "Offline mode could not" in warning:
        st.error(warning)

overview_tab, table_tab, charts_tab, report_tab, checklist_tab, downloads_tab = st.tabs(
    ["Overview", "Table", "Charts", "Report", "Street View checklist", "Downloads"]
)

with overview_tab:
    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.markdown(
            '<div class="map-panel-title">Map</div>',
            unsafe_allow_html=True,
        )
        if display_df.empty:
            focus_options = [0]
            focus_format = lambda _: "No gaps available"
        else:
            rank_values = [int(value) for value in display_df["rank"].dropna().tolist()]
            focus_options = [0] + rank_values
            focus_format = lambda value: "No focus" if value == 0 else f"#{value}"
        focus_label_col, focus_select_col = st.columns([0.55, 1], gap="small", vertical_alignment="center")
        with focus_label_col:
            st.markdown('<div class="focus-gap-label">Focus on gap</div>', unsafe_allow_html=True)
        with focus_select_col:
            focus_rank = st.selectbox(
                "Focus on gap #",
                focus_options,
                format_func=focus_format,
                key=f"focus_{chosen_view}_{run_id}",
                label_visibility="collapsed",
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
        with st.container(key="top-gap-heading"):
            st.markdown("Top gaps")
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
                    score_text = f"{score_value:.1f}" if pd.notna(score_value) else "N/A"
                    with st.container(border=True):
                        st.markdown(
                            f'<div class="gap-card"><div class="gap-card-title">#{rank} {html.escape(name)}</div>'
                            f'<div class="gap-card-meta">{html.escape(place_type)} · {html.escape(distance_text)}'
                            f' · Score {score_text}'
                            f' · <span class="gap-confidence">{html.escape(confidence)}</span></div></div>',
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
