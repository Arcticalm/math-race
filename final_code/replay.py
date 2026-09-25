"""Read published schedules and replay fixed transport choices in continuous time."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from final_code.problem2.patterns import replay
from final_code.problem2.transport import _charge_duration, load_task_boxes


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def load_transport(directory: Path, evaluator):
    """Keep recorded times and energies so the independent audit can reject them."""
    boxes = {box.code: box for box in load_task_boxes()}
    delivery_rows = read_csv(directory / "box_delivery_audit.csv")
    groups, delivered = {}, {}
    seen = set()
    for row in delivery_rows:
        if row["货箱编号"] in seen:
            raise ValueError(f"Duplicate published box: {row['货箱编号']}")
        seen.add(row["货箱编号"])
        box = boxes[row["货箱编号"]]
        if row["服务区编号"] != box.site:
            raise ValueError(f"Published box site differs from source: {box.code}")
        if row.get("质量（kg）") and abs(float(row["质量（kg）"]) - box.mass_kg) > 1e-9:
            raise ValueError(f"Published box mass differs from source: {box.code}")
        code = row["架次编号"]
        groups.setdefault(code, []).append(box)
        delivered.setdefault(code, {})[box.code] = float(row["交付完成时刻（s）"])
    path = directory / "sorties_audit.csv"
    if not path.exists():
        path = directory / "transport_inherited_audit.csv"
    result = []
    task_rows = read_csv(path)
    if set(groups) != {row["架次编号"] for row in task_rows}:
        raise ValueError("Published deliveries contain missing or unknown sorties")
    for row in task_rows:
        code = row["架次编号"]
        if row.get("逐箱交付数") and int(row["逐箱交付数"]) != len(groups[code]):
            raise ValueError(f"Published box count mismatch: {code}")
        route = [site for site in re.split(r"[,，→]", row["访问服务区顺序"]) if site]
        physical = evaluator.evaluate(groups[code], route, row["机型编号"])
        if physical is None:
            raise ValueError(f"Published transport is physically infeasible: {code}")
        sortie = replay(physical, evaluator, float(row["准备开始时刻（s）"]), code)
        sortie.drone, sortie.battery = row["无人机编号"], row["电池编号"]
        sortie.return_s = float(row["返回O01时刻（s）"])
        sortie.energy_kwh = float(row["架次能耗（kWh）"])
        sortie.battery_soc_return_percent = float(row["返航SOC（%）"])
        sortie.takeoff_s = float(row.get("起飞时刻（s）", row.get("装载完成/起飞时刻（s）")))
        sortie.deliveries = delivered[code]
        result.append(sortie)
    return result


def left_shift_transport(sorties, evaluator, batteries):
    """Earliest starts with fixed drone/battery orders; valid only for pure Q2.

    The original time order is a topological order of both resource chains.
    Every start weakly decreases, hence hard deadlines remain satisfied. The
    method is exact for these fixed chains, not for route or resource choices.
    """
    drone_ready, battery_ready = {}, {}
    battery_by_code = {battery.code: battery for battery in batteries}
    result = []
    for previous in sorted(sorties, key=lambda sortie: (sortie.prep_start_s, sortie.code)):
        start = max(drone_ready.get(previous.drone, 0.0),
                    battery_ready.get(previous.battery, 0.0))
        sortie = replay(previous, evaluator, start)
        result.append(sortie)
        drone_ready[sortie.drone] = sortie.return_s
        battery_ready[sortie.battery] = sortie.return_s + _charge_duration(
            battery_by_code[sortie.battery].full_charge_s,
            sortie.battery_soc_return_percent / 100)
    return result
