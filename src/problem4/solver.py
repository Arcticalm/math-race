from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "无人机应急物资运输基础数据"
DEFAULT_INPUT = ROOT / "outputs" / "problem3"
DEFAULT_OUTPUT = ROOT / "outputs" / "problem4"
SITES = tuple(f"S{i:03d}" for i in range(1, 16))
AIR_TYPES = ("A", "B", "C")
RESOURCE_KEYS = ("A_airframe", "B_airframe", "C_airframe", "A_battery", "B_battery", "C_battery", "relay_airframe", "relay_energy")


def _csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _float(row: dict, *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return float(row[name])
    return default


def _sites(value: str) -> tuple[str, ...]:
    return tuple(sorted(set(x.strip() for x in value.split(",") if x.strip().startswith("S"))))


def load_inventory() -> dict[str, int]:
    """Read counts from the source workbooks; constants are never used as fallback."""
    path = DATA / "运输无人机数据.xlsx"
    rows = list(load_workbook(path, read_only=True, data_only=True).active.iter_rows(values_only=True))
    counts = {f"{kind}_airframe": 0 for kind in AIR_TYPES}
    batteries = {f"{kind}_battery": 0 for kind in AIR_TYPES}
    section = None
    for row in rows:
        if row[0] == "逐架无人机清单":
            section = "drones"
        elif row[0] in AIR_TYPES and isinstance(row[1], (int, float)):
            batteries[f"{row[0]}_battery"] = int(row[1])
        elif section == "drones" and row[0] and str(row[0]).startswith("U"):
            counts[f"{row[1]}_airframe"] += 1
    result = {**counts, **batteries}
    relay_rows = list(load_workbook(DATA / "中继无人机数据.xlsx", read_only=True, data_only=True).active.iter_rows(values_only=True))
    relay_count = sum(1 for row in relay_rows if row[0] and str(row[0]).startswith("R0"))
    result["relay_airframe"] = relay_count
    # Energy component inventory is the explicit component list in the source workbook.
    for row in relay_rows:
        if row[0] == "R" and isinstance(row[1], (int, float)):
            result["relay_energy"] = int(row[1])
            break
    if not result.get("relay_energy"):
        raise ValueError("中继能源组件库存缺失，不能据猜测填补库存")
    return result


def q3_gate(input_dir: Path) -> dict:
    screening_path = input_dir / "screening.json"
    if not screening_path.exists():
        return {"ready": False, "reason": "缺少 Q3 screening.json"}
    screening = json.loads(screening_path.read_text(encoding="utf-8"))
    required = (input_dir / "transport_inherited_audit.csv", input_dir / "relay_schedule.csv", input_dir / "relay_resource_audit.csv")
    missing = [str(path.name) for path in required if not path.exists()]
    if missing:
        return {"ready": False, "reason": f"缺少 Q3 输出: {', '.join(missing)}", "screening": screening}
    if screening.get("feasible") is not True or screening.get("continuity_certified") is not True:
        return {"ready": False, "reason": "Q3 联合方案或通信连续性审计未通过", "screening": screening}
    return {"ready": True, "screening": screening}


def read_q3(input_dir: Path) -> tuple[list[dict], list[dict]]:
    transport = _csv(input_dir / "transport_inherited_audit.csv")
    relay = _csv(input_dir / "relay_schedule.csv")
    if not transport or any(not _sites(row.get("访问服务区顺序", "")) for row in transport):
        raise ValueError("Q3 运输审计缺少服务区访问关系")
    return transport, relay


def atomic_units(transport: list[dict], relay: list[dict]) -> list[frozenset[str]]:
    parent = {site: site for site in SITES}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        a, b = find(a), find(b)
        if a != b: parent[b] = a
    for row in transport:
        sites = _sites(row["访问服务区顺序"])
        for site in sites[1:]: union(sites[0], site)
    by_relay = defaultdict(set)
    for row in relay:
        covered = row.get("covered_sorties") or row.get("保障运输架次", "")
        by_relay[row.get("relay_sortie", row.get("中继架次编号", ""))].update(x.strip() for x in covered.split(",") if x.strip())
    by_sortie = {row.get("架次编号", ""): _sites(row.get("访问服务区顺序", "")) for row in transport}
    for sorties in by_relay.values():
        sites = [site for sortie in sorties for site in by_sortie.get(sortie, ())]
        for site in sites[1:]: union(sites[0], site)
    groups = defaultdict(set)
    for site in SITES: groups[find(site)].add(site)
    return sorted((frozenset(group) for group in groups.values()), key=lambda group: min(group))


def partitions(units: list[frozenset[str]], k: int) -> list[tuple[frozenset[str], ...]]:
    if len(units) < k: return []
    result = []
    def visit(index, groups):
        if index == len(units):
            if len(groups) == k: result.append(tuple(frozenset().union(*group) for group in groups))
            return
        unit = units[index]
        for group in groups:
            group.append(unit); visit(index + 1, groups); group.pop()
        if len(groups) < k: groups.append([unit]); visit(index + 1, groups); groups.pop()
    visit(0, [])
    return sorted(set(tuple(sorted(p, key=lambda x: min(x))) for p in result), key=lambda p: tuple(sorted(min(x) for x in p)))


def _peak(intervals: list[tuple[float, float]]) -> int:
    events = [(start, 1) for start, end in intervals if end > start] + [(end, -1) for start, end in intervals if end > start]
    active = peak = 0
    for _, change in sorted(events, key=lambda item: (item[0], item[1])):
        active += change; peak = max(peak, active)
    return peak


def _charge_s(soc_percent: float, full_s: float) -> float:
    s = max(0.0, min(1.0, soc_percent / 100.0))
    return full_s * (0.65 * (0.90 - s) / 0.90 + 0.35 if s < 0.90 else 0.35 * (1 - s) / 0.10)


def resource_intervals(transport: list[dict], relay: list[dict]) -> dict[str, list[tuple[float, float, str]]]:
    values = defaultdict(list)
    battery_full = {"A": 1800.0, "B": 2400.0, "C": 3000.0}
    for row in transport:
        kind = row["机型编号"]
        start, end = _float(row, "准备开始时刻（s）", "开始时刻（s）"), _float(row, "返回O01时刻（s）")
        values[f"{kind}_airframe"].append((start, end, row["架次编号"]))
        soc = _float(row, "返航SOC（%）", default=0.0)
        full = battery_full[kind]
        values[f"{kind}_battery"].append((start, end + _charge_s(soc, full), row["架次编号"]))
    for row in relay:
        start = _float(row, "开始时刻（s）", "service_start_s", default=0)
        end = _float(row, "机体再次可用（s）", default=0.0)
        if not end:
            end = _float(row, "返回O01时刻（s）", "return_o01_s", default=start) + 300.0
        values["relay_airframe"].append((start, end, row.get("中继架次编号", row.get("relay_sortie", "relay"))))
        component_end = _float(row, "能源组件再次可用（s）", default=0.0)
        if not component_end:
            component_end = _float(row, "返回O01时刻（s）", "return_o01_s", default=start) + _charge_s(_float(row, "返航SOC（%）", "return_soc_percent", default=0), 1800)
        values["relay_energy"].append((start, component_end, row.get("中继架次编号", "relay")))
    return values


def evaluate_partition(groups, transport, relay, inventory):
    site_to_group = {site: index for index, group in enumerate(groups, 1) for site in group}
    task_group = {}
    for row in transport:
        memberships = {site_to_group[s] for s in _sites(row["访问服务区顺序"])}
        if len(memberships) != 1: raise ValueError(f"运输架次跨组: {row['架次编号']}")
        task_group[row["架次编号"]] = memberships.pop()
    for row in relay:
        covered = [item.strip() for item in (row.get("covered_sorties", "") or "").split(",") if item.strip()]
        memberships = {task_group[item] for item in covered if item in task_group}
        if covered and len(memberships) != 1:
            raise ValueError(f"中继架次跨组或缺少运输映射: {row.get('relay_sortie', row.get('中继架次编号', ''))}")
        task_group[row.get("relay_sortie", row.get("中继架次编号", "relay"))] = memberships.pop() if memberships else 1
    intervals = resource_intervals(transport, relay)
    rows = []
    for index, group in enumerate(groups, 1):
        demand = {}
        for key in RESOURCE_KEYS:
            demand[key] = _peak([(a, b) for a, b, task in intervals[key] if task_group.get(task, index) == index])
        rows.append({"group": index, "sites": ",".join(sorted(group)), **demand,
                     "transport_sorties": ",".join(sorted(task for task, gid in task_group.items() if gid == index))})
    return rows


def run(input_dir: Path = DEFAULT_INPUT, output_dir: Path = DEFAULT_OUTPUT) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    gate = q3_gate(input_dir)
    if not gate["ready"]:
        result = {"status": "等待 Q3 最终方案", "q3_gate": gate}
        (output_dir / "status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    transport, relay = read_q3(input_dir)
    inventory = load_inventory()
    units = atomic_units(transport, relay)
    result = {"status": "ready", "inventory": inventory, "atomic_units": [sorted(x) for x in units], "partitions": {}}
    for k in (2, 3):
        candidates = partitions(units, k)
        result["partitions"][str(k)] = [evaluate_partition(candidate, transport, relay, inventory) for candidate in candidates]
    (output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.output), ensure_ascii=False, indent=2))
