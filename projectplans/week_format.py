"""Formatting helpers for ISO year/week labels shown in the UI."""


def format_year_week(year: int, week: int) -> str:
    """Return the compact UI form, e.g. ISO 2026 week 15 as ``wk2615``."""
    return f"wk{year % 100:02d}{week:02d}"
