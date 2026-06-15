"""Temporal expression parsing and normalization to OWL-Time intervals."""
from __future__ import annotations

import re


def parse_when(when_text: str) -> dict | None:
    """Parse a when expression to structured temporal info.

    Returns dict with keys: start_year, end_year, raw_expression, precision.
    """
    if not when_text or when_text.strip().casefold() in ("not stated", "nan", "none", ""):
        return None

    text = when_text.strip()
    result = {"raw": text, "start_year": None, "end_year": None, "precision": "unknown"}

    # Exact date patterns: "May 1944", "1944-05", "March 15, 1942"
    date_match = re.search(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s+(1[89]\d{2}|20\d{2})", text, re.IGNORECASE)
    if date_match:
        y = int(date_match.group(1))
        result["start_year"] = y
        result["end_year"] = y
        result["precision"] = "month"
        return result

    month_year = re.search(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(1[89]\d{2}|20\d{2})", text, re.IGNORECASE)
    if month_year:
        y = int(month_year.group(1))
        result["start_year"] = y
        result["end_year"] = y
        result["precision"] = "month"
        return result

    # Year ranges: "1942-1945", "from 1939 to 1945"
    range_match = re.search(r"(1[89]\d{2}|20\d{2})\s*[-–to]+\s*(1[89]\d{2}|20\d{2})", text)
    if range_match:
        y1, y2 = int(range_match.group(1)), int(range_match.group(2))
        result["start_year"] = min(y1, y2)
        result["end_year"] = max(y1, y2)
        result["precision"] = "year_range"
        return result

    # Single years
    years = [int(y) for y in re.findall(r"\b(1[89]\d{2}|20\d{2})\b", text)]
    if years:
        result["start_year"] = min(years)
        result["end_year"] = max(years)
        result["precision"] = "year" if len(years) == 1 else "year_range"
        return result

    # Relative expressions
    relative_patterns = {
        "pre_war": [r"\bbefore the war\b", r"\bpre[- ]?war\b", r"\bbefore 1939\b"],
        "during_war": [r"\bduring the war\b", r"\bwar years?\b", r"\bwartime\b"],
        "post_war": [r"\bafter the war\b", r"\bpost[- ]?war\b", r"\bafter liberation\b"],
        "childhood": [r"\bas a child\b", r"\bchildhood\b", r"\bwhen .* young\b"],
    }
    for period, patterns in relative_patterns.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            result["precision"] = "relative"
            result["period"] = period
            if period == "pre_war":
                result["end_year"] = 1939
            elif period == "during_war":
                result["start_year"] = 1939
                result["end_year"] = 1945
            elif period == "post_war":
                result["start_year"] = 1945
            return result

    return result if result["precision"] != "unknown" else None


def temporal_bucket(when_info: dict | None) -> str | None:
    """Assign a temporal bucket for analysis grouping."""
    if not when_info:
        return None
    sy = when_info.get("start_year")
    ey = when_info.get("end_year")
    period = when_info.get("period")

    if period:
        return period

    if sy and ey:
        mid = (sy + ey) / 2
        if mid < 1933:
            return "pre_nazi"
        elif mid < 1939:
            return "nazi_rise"
        elif mid < 1942:
            return "early_war"
        elif mid <= 1945:
            return "late_war_holocaust"
        elif mid <= 1950:
            return "immediate_postwar"
        else:
            return "later_life"
    return None
