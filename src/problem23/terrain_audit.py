"""Independently audit cruise clearance by segment/rectangle intersections."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def intersected_ground(dem, start, end) -> tuple[float, int]:
    """Clip the segment against each candidate cell, independently of sample_leg.

    Cells are closed rectangles: touching an edge or a corner counts. Elevations
    follow the supplied raster; this is a horizontal-cruise clearance check.
    """
    inverse = ~dem.transform
    x0, y0 = inverse * (start.longitude, start.latitude)
    x1, y1 = inverse * (end.longitude, end.latitude)
    if any(not (0 <= x <= dem.width and 0 <= y <= dem.height)
           for x, y in ((x0, y0), (x1, y1))):
        raise ValueError("Audit segment leaves DEM extent")
    left = max(0, math.floor(min(x0, x1)) - 1)
    right = min(dem.width, math.floor(max(x0, x1)) + 1)
    top = max(0, math.floor(min(y0, y1)) - 1)
    bottom = min(dem.height, math.floor(max(y0, y1)) + 1)
    rows, cols = np.mgrid[top:bottom, left:right]
    enter = np.zeros(rows.shape, dtype=float)
    leave = np.ones(rows.shape, dtype=float)
    valid = np.ones(rows.shape, dtype=bool)
    for origin, delta, lower in ((x0, x1 - x0, cols), (y0, y1 - y0, rows)):
        if delta == 0:
            valid &= (lower <= origin) & (origin <= lower + 1)
        else:
            a = (lower - origin) / delta
            b = (lower + 1 - origin) / delta
            enter = np.maximum(enter, np.minimum(a, b))
            leave = np.minimum(leave, np.maximum(a, b))
    valid &= enter <= leave + 1e-12
    raster = dem.read(1, window=((top, bottom), (left, right)), masked=True)
    heights = raster[valid]
    if not heights.size or np.any(np.ma.getmaskarray(heights)) or not np.all(np.isfinite(heights.data)):
        raise ValueError("Audit segment crosses missing DEM data")
    return float(heights.max()), int(heights.size)


def audit_clearance(sorties, evaluator) -> dict:
    nodes = {"O01": evaluator.base, **evaluator.sites}
    checked = {}
    rows = []
    for sortie in sorties:
        for sequence, leg in enumerate(sortie.legs or [], 1):
            pair = (leg["from"], leg["to"])
            if pair not in checked:
                checked[pair] = intersected_ground(evaluator.dem, nodes[pair[0]], nodes[pair[1]])
            maximum, cell_count = checked[pair]
            clearance = leg["cruise_altitude_m"] - maximum
            rows.append({
                "sortie": sortie.code, "leg": sequence, "from": pair[0], "to": pair[1],
                "intersected_cell_count": cell_count, "maximum_ground_m": maximum,
                "cruise_altitude_m": leg["cruise_altitude_m"], "minimum_clearance_m": clearance,
                "compliant": clearance >= 50.0 - 1e-9,
            })
    return {
        "method": "independent segment/closed-cell rectangle intersection",
        "scope": "horizontal cruise; departure/arrival work heights follow the task statement",
        "required_clearance_m": 50.0,
        "minimum_clearance_m": min(row["minimum_clearance_m"] for row in rows),
        "unique_directed_leg_count": len(checked), "leg_count": len(rows),
        "feasible": all(row["compliant"] for row in rows),
        "violation_count": sum(not row["compliant"] for row in rows),
        "legs": rows,
    }


def write_clearance_outputs(output_dir: Path, report: dict) -> None:
    rows = report["legs"]
    with (output_dir / "terrain_clearance_audit.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    unique = {(row["from"], row["to"]): row for row in rows}
    labels = [f"{a}→{b}" for a, b in unique]
    values = list(unique.values())
    fig, ax = plt.subplots(figsize=(14, 6), layout="constrained")
    ax.plot(labels, [row["maximum_ground_m"] for row in values], "o-", label="Maximum intersected DEM elevation")
    ax.plot(labels, [row["cruise_altitude_m"] for row in values], "o-", label="Planned cruise altitude")
    ax.set(title=f"Cruise clearance audit: minimum {report['minimum_clearance_m']:.3f} m",
           xlabel="Directed flight leg", ylabel="Elevation (m)")
    ax.tick_params(axis="x", labelrotation=90, labelsize=8)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.savefig(output_dir / "terrain_clearance.png", dpi=180)
    plt.close(fig)
