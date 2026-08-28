"""用V2模型预测水肥量，并生成三肥罐四阀工作单。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

try:
    from .build_job import build_job
    from .recommend import CONFIG
    from .train_policy_v2 import CATEGORICAL, NUMERIC, estimate_fc, stage_for, weather_features
except ImportError:
    from build_job import build_job
    from recommend import CONFIG
    from train_policy_v2 import CATEGORICAL, NUMERIC, estimate_fc, stage_for, weather_features


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = joblib.load(ROOT / "models" / "hohhot_fertigation_policy_v2.joblib")
SOILS = json.loads((ROOT / "configs" / "soil_profiles.json").read_text(encoding="utf-8"))["profiles"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD，历史演示范围2015-2025")
    p.add_argument("--crop", required=True, choices=CONFIG["crops"].keys())
    p.add_argument("--stage")
    p.add_argument("--allow-stage-override", action="store_true")
    p.add_argument("--soil-profile", default="土默川中", choices=[x["name"] for x in SOILS])
    p.add_argument("--area-mu", type=float, required=True)
    p.add_argument("--moisture20", type=float, required=True)
    p.add_argument("--moisture40", type=float, required=True)
    p.add_argument("--moisture60", type=float, required=True)
    p.add_argument("--field-capacity", type=float)
    p.add_argument("--soil-ec", type=float, default=1.0)
    p.add_argument("--soil-n-level", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--soil-p-level", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--soil-k-level", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--days-since-fertigation", type=int, default=8)
    p.add_argument("--n-applied-stage", type=float, default=0)
    p.add_argument("--p-applied-stage", type=float, default=0)
    p.add_argument("--k-applied-stage", type=float, default=0)
    args = p.parse_args()
    date = pd.Timestamp(args.date)
    weather = weather_features()
    if date not in weather.index:
        raise SystemExit("日期不在当前NASA POWER历史数据范围内；实时版应由Open-Meteo现场适配器构造同字段输入")
    w = weather.loc[date]
    soil = next(x for x in SOILS if x["name"] == args.soil_profile)
    fc = args.field_capacity or estimate_fc(soil)
    calendar_stage = stage_for(args.crop, date.dayofyear)
    stage = args.stage or calendar_stage
    if stage not in CONFIG["crops"][args.crop]["stages"]:
        raise SystemExit("日期不在作物示例生育期，或stage无效")
    if args.stage and args.stage != calendar_stage and not args.allow_stage_override:
        raise SystemExit(f"输入stage={args.stage}与示例日历stage={calendar_stage}不一致；现场确认后才可加 --allow-stage-override")
    s = CONFIG["crops"][args.crop]["stages"][stage]
    crop_cfg = CONFIG["crops"][args.crop]
    moisture = np.array([args.moisture20, args.moisture40, args.moisture60])
    weights = np.array([0.55, 0.30, 0.15]) if s["root_depth_m"] >= 0.6 else np.array([0.7, 0.3, 0])
    root_m = float(np.dot(moisture, weights) / weights.sum())
    factor = {"low": 1.0, "medium": 0.65, "high": 0.0}
    row = {
        "crop": args.crop, "stage": stage, "soil_n_level": args.soil_n_level, "soil_p_level": args.soil_p_level,
        "soil_k_level": args.soil_k_level, "soil_profile": args.soil_profile, "doy": date.dayofyear,
        "t_mean": w.T2M, "t_max": w.T2M_MAX, "t_min": w.T2M_MIN, "rh": w.RH2M, "wind": w.WS2M,
        "radiation": w.ALLSKY_SFC_SW_DWN, "rain_today": w.PRECTOTCORR, "rain_next_2d": w.rain_next_2d,
        "eto": w.eto, "gdd10_14d": w.gdd10_14d, "rain_7d": w.rain_7d, "eto_7d": w.eto_7d,
        "dry_days": w.dry_days, "field_capacity": fc, "moisture20": moisture[0], "moisture40": moisture[1],
        "moisture60": moisture[2], "soil_ec": args.soil_ec, "soil_ph": soil["ph"], "soc_g_kg": soil["soc_g_kg"],
        "soil_n_g_kg": soil["nitrogen_g_kg"], "sand_pct": soil["sand_pct"], "clay_pct": soil["clay_pct"],
        "bulk_density": soil["bulk_density"], "days_since_fertigation": args.days_since_fertigation,
        "n_applied_stage": args.n_applied_stage, "p_applied_stage": args.p_applied_stage, "k_applied_stage": args.k_applied_stage,
        "root_depth": s["root_depth_m"], "root_moisture": root_m, "relative_fc": root_m / fc,
        "trigger_fc": s["trigger_fc"], "target_fc": s["target_fc"], "kc": s["kc"],
        "n_remaining": max(0, crop_cfg["season_n_kg_mu"] * s["n_share"] - args.n_applied_stage),
        "p_remaining": max(0, crop_cfg["season_p2o5_kg_mu"] * s["p_share"] - args.p_applied_stage),
        "k_remaining": max(0, crop_cfg["season_k2o_kg_mu"] * s["k_share"] - args.k_applied_stage),
        "n_level_factor": factor[args.soil_n_level], "p_level_factor": factor[args.soil_p_level],
        "k_level_factor": factor[args.soil_k_level], "fertilizer_interval_ready": int(args.days_since_fertigation >= 7),
        "ec_block": int(args.soil_ec >= 2.0), "latitude": float(soil["latitude"]),
        "longitude": float(soil["longitude"]), "co2_ppm": 420.0,
        "soil_temperature_c": float(w.T2M), "soil_n_mg_kg": float(soil["nitrogen_g_kg"] * 1000),
        "soil_p_mg_kg": float(soil.get("phosphorus_mg_kg", 20.0)),
        "soil_k_mg_kg": float(soil.get("potassium_mg_kg", 160.0)),
        "light_lux": float(max(0.0, w.ALLSKY_SFC_SW_DWN) * 120.0),
        "rain_24h_mm": float(w.PRECTOTCORR),
    }
    pred = np.maximum(0, PACKAGE["pipeline"].predict(pd.DataFrame([row])[CATEGORICAL + NUMERIC])[0])
    # 部署安全护栏：接近0的树平均值归零，并应用绝对事件上限。
    physical_irrigation_gate = (root_m / fc <= s["trigger_fc"] and w.rain_next_2d < max(5.0, s["kc"] * w.eto))
    water = min(25.0, pred[0]) if physical_irrigation_gate and pred[0] >= 0.5 else 0.0
    fertilizer_gate = water > 0 and args.soil_ec < 2.0 and args.days_since_fertigation >= 7
    if not fertilizer_gate:
        pred[1:] = 0
    if args.soil_n_level == "high": pred[1] = 0
    if args.soil_p_level == "high": pred[2] = 0
    if args.soil_k_level == "high": pred[3] = 0
    pred[1] = min(pred[1], row["n_remaining"])
    pred[2] = min(pred[2], row["p_remaining"])
    pred[3] = min(pred[3], row["k_remaining"])
    pred[1:] = np.where(pred[1:] < 0.05, 0, pred[1:])
    decision = {"crop": args.crop, "stage": stage, "irrigation_m3_mu": round(water, 1),
                "nitrogen_kg_mu": round(min(2.5, pred[1]), 2), "p2o5_kg_mu": round(min(1.5, pred[2]), 2),
                "k2o_kg_mu": round(min(3.0, pred[3]), 2), "model": "hohhot_fertigation_policy_v2",
                "warning": PACKAGE["metrics"]["warning"]}
    print(json.dumps({"decision": decision, "job": build_job(args.area_mu, decision)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
