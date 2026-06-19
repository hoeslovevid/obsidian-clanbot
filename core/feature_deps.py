"""Warnings when toggling features that affect other modules."""
from __future__ import annotations

FEATURE_DEPENDENCIES: dict[str, list[str]] = {
    "economy_passive": ["pets", "gambling"],
    "pets": ["economy_passive"],
    "gambling": ["economy_passive"],
    "trade": ["economy_passive"],
    "lfg": ["notifications"],
    "events": ["notifications"],
}


def dependency_warning(feature: str, turning_off: bool) -> str | None:
    """Return extra modal text when disabling a feature with dependents."""
    if not turning_off:
        return None
    deps = FEATURE_DEPENDENCIES.get(feature)
    if not deps:
        return None
    names = ", ".join(f"`{d}`" for d in deps)
    return (
        f"\n\n⚠️ Members also use **{names}** alongside `{feature}`. "
        "Consider toggling those off too if you want a full shutdown."
    )
