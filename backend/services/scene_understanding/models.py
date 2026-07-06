"""Models for scene object extraction."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtractedObjects:
    """Visual objects identified for a single scene."""

    primary_objects: list[str] = field(default_factory=list)
    secondary_objects: list[str] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    mechanical_components: list[str] = field(default_factory=list)
    historical_figures: list[str] = field(default_factory=list)

    def all_objects(self) -> list[str]:
        """Deduplicated union of all object categories."""
        seen: set[str] = set()
        ordered: list[str] = []
        for item in (
            self.primary_objects
            + self.secondary_objects
            + self.brands
            + self.locations
            + self.mechanical_components
            + self.historical_figures
        ):
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                ordered.append(item.strip())
        return ordered

    def summary_labels(self) -> list[str]:
        """Compact list for debug output (primary first)."""
        labels = list(self.primary_objects)
        for item in self.all_objects():
            if item not in labels:
                labels.append(item)
        return labels

    def to_prompt_block(self) -> str:
        lines = []
        if self.primary_objects:
            lines.append(f"Primary objects: {', '.join(self.primary_objects)}")
        if self.secondary_objects:
            lines.append(f"Secondary objects: {', '.join(self.secondary_objects)}")
        if self.brands:
            lines.append(f"Brands: {', '.join(self.brands)}")
        if self.locations:
            lines.append(f"Locations: {', '.join(self.locations)}")
        if self.mechanical_components:
            lines.append(f"Mechanical components: {', '.join(self.mechanical_components)}")
        if self.historical_figures:
            lines.append(f"Historical figures: {', '.join(self.historical_figures)}")
        return "\n".join(lines)
