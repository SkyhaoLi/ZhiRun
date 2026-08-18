"""把农艺模型输出转换为四电磁阀可执行的流量闭环工作单。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .recommend import recommend, CONFIG
except ImportError:  # 允许 `python scripts/build_job.py` 直接运行
    from recommend import recommend, CONFIG


ROOT = Path(__file__).resolve().parents[1]
HARDWARE = json.loads((ROOT / "configs" / "hardware.json").read_text(encoding="utf-8"))


def build_job(area_mu: float, decision: dict, hardware: dict = HARDWARE) -> dict:
    if area_mu <= 0:
        raise ValueError("area_mu必须大于0")
    water_l = decision["irrigation_m3_mu"] * area_mu * 1000
    nutrient_keys = {"N": "nitrogen_kg_mu", "P2O5": "p2o5_kg_mu", "K2O": "k2o_kg_mu"}
    doses = []
    for valve, line in hardware["fertilizer_lines"].items():
        nutrient = line["nutrient"]
        kg = decision[nutrient_keys[nutrient]] * area_mu
        target_l = kg * 1000 / line["concentration_g_l"] if kg > 0 else 0.0
        if target_l > 0:
            doses.append({
                "valve": valve,
                "nutrient": nutrient,
                "target_nutrient_kg": round(kg, 3),
                "target_solution_l": round(target_l, 3),
                "close_at_meter_l": round(target_l, 3),
            })
    if water_l <= 0:
        doses = []
    preflush = min(water_l, max(hardware["main"]["minimum_preflush_l"], water_l * hardware["main"]["preflush_fraction"])) if water_l else 0
    postflush = min(max(0.0, water_l - preflush), max(hardware["main"]["minimum_postflush_l"], water_l * hardware["main"]["postflush_fraction"])) if water_l else 0
    phases = []
    if water_l:
        phases.append({"state": "PREFLUSH", "main_water_target_l": round(preflush, 1), "open_valves": ["WATER"]})
        for index, dose in enumerate(doses):
            phases.append({"state": f"DOSE_{dose['valve']}", "target_solution_l": dose["target_solution_l"],
                           "open_valves": ["WATER", dose["valve"]], "close_condition": f"{dose['valve']}_meter >= target"})
            if index < len(doses) - 1:
                phases.append({"state": "INTER_TANK_FLUSH", "main_water_target_l": hardware["control"]["inter_tank_flush_l"],
                               "open_valves": ["WATER"]})
        phases.append({"state": "IRRIGATE_AND_POSTFLUSH", "main_water_close_at_total_l": round(water_l, 1),
                       "minimum_clean_postflush_l": round(postflush, 1), "open_valves": ["WATER"]})
    phases.append({"state": "COMPLETE" if water_l else "IDLE", "open_valves": []})
    return {
        "area_mu": area_mu,
        "crop": decision["crop"],
        "stage": decision["stage"],
        "target_main_water_l": round(water_l, 1),
        "doses": doses,
        "phases": phases,
        "interlocks": ["主水无流量时所有肥阀关闭", "肥路无流量/超流量立即关闭对应肥阀", "任一时刻最多开启一路肥阀",
                       "母液累计达到目标体积即关阀", "故障时先关肥阀再关主水阀并报警"],
        "hardware_warning": hardware["warning"],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--crop", required=True, choices=CONFIG["crops"].keys())
    p.add_argument("--stage", required=True)
    p.add_argument("--area-mu", type=float, required=True)
    p.add_argument("--soil-moisture-20", type=float, required=True)
    p.add_argument("--soil-moisture-40", type=float)
    p.add_argument("--soil-moisture-60", type=float)
    p.add_argument("--field-capacity", type=float, required=True)
    p.add_argument("--rain-forecast", type=float, default=0)
    p.add_argument("--eto", type=float, required=True)
    p.add_argument("--days-since-fertigation", type=int, default=8)
    p.add_argument("--soil-ec", type=float)
    p.add_argument("--soil-test-n-level", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--soil-test-p-level", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--soil-test-k-level", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--n-applied-stage", type=float, default=0)
    p.add_argument("--p-applied-stage", type=float, default=0)
    p.add_argument("--k-applied-stage", type=float, default=0)
    args = p.parse_args()
    moisture = [v for v in (args.soil_moisture_20, args.soil_moisture_40, args.soil_moisture_60) if v is not None]
    decision = recommend(args.crop, args.stage, moisture, args.field_capacity, args.rain_forecast, args.eto,
                         args.days_since_fertigation, args.soil_ec, args.n_applied_stage, args.p_applied_stage,
                         args.k_applied_stage, args.soil_test_n_level, args.soil_test_p_level, args.soil_test_k_level)
    print(json.dumps({"decision": decision, "job": build_job(args.area_mu, decision)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
