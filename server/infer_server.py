#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智润水肥一体化策略推理服务。"""
import json
import os
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)
MODEL_DIR = os.environ.get("ZHIRUN_FERTIGATION_MODEL_DIR", os.path.join(PROJECT_ROOT, "灌溉模型", "灌溉模型"))
PORT = int(os.environ.get("ZHIRUN_INFER_PORT", "10001"))

_lock = threading.Lock()
_state = {"loaded": False, "loading": False, "error": None, "hint": None}
_package = _config = _soils = _weather = None


def load_model():
    global _package, _config, _soils, _weather
    with _lock:
        if _state["loaded"] or _state["loading"]:
            return _state["loaded"]
        _state.update({"loading": True, "error": None, "hint": None})
    try:
        import joblib
        import numpy as np
        import pandas as pd
        if MODEL_DIR not in sys.path:
            sys.path.insert(0, os.path.join(MODEL_DIR, "scripts"))
        from train_policy_v2 import CATEGORICAL, NUMERIC, estimate_fc, stage_for, weather_features
        model_path = os.path.join(MODEL_DIR, "models", "hohhot_fertigation_policy_v2.joblib")
        _package = joblib.load(model_path)
        _config = json.load(open(os.path.join(MODEL_DIR, "configs", "crops.json"), encoding="utf-8"))
        _soils = json.load(open(os.path.join(MODEL_DIR, "configs", "soil_profiles.json"), encoding="utf-8"))["profiles"]
        _weather = weather_features()
        _package.update({"np": np, "pd": pd, "categorical": CATEGORICAL, "numeric": NUMERIC,
                         "estimate_fc": estimate_fc, "stage_for": stage_for})
        with _lock:
            _state.update({"loaded": True, "loading": False})
        print("[infer] 水肥策略模型已加载:", model_path)
        return True
    except Exception as exc:
        with _lock:
            _state.update({"loaded": False, "loading": False, "error": str(exc),
                           "hint": "请在灌溉模型目录执行: python -m pip install -r requirements.txt"})
        return False


def number(body, key, default, low=None, high=None):
    value = body.get(key, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(key + " 必须为数字")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(key + " 超出允许范围")
    return value


def build_job(body, decision):
    area = number(body, "area_mu", 1, 0.01, 100000)
    main_flow = number(body, "main_flow_l_min", 60, 0.01, 10000)
    water_l = decision["irrigation_m3_mu"] * area * 1000
    lines = (("A", "N", "nitrogen_kg_mu", "a_concentration_g_l", "a_flow_l_min"),
             ("B", "P2O5", "p2o5_kg_mu", "b_concentration_g_l", "b_flow_l_min"),
             ("C", "K2O", "k2o_kg_mu", "c_concentration_g_l", "c_flow_l_min"))
    doses = []
    for valve, nutrient, key, concentration_key, flow_key in lines:
        concentration = number(body, concentration_key, 0, 0, 2000)
        flow = number(body, flow_key, 0, 0, 100)
        nutrient_kg = decision[key] * area
        if nutrient_kg <= 0:
            continue
        if concentration <= 0 or flow <= 0:
            raise ValueError(valve + " 路有施肥建议，请填写有效的母液浓度和流量")
        solution_l = nutrient_kg * 1000 / concentration
        doses.append({"valve": valve, "nutrient": nutrient, "nutrient_kg": round(nutrient_kg, 3),
                      "solution_l": round(solution_l, 2), "flow_l_min": round(flow, 2),
                      "estimated_seconds": round(solution_l / flow * 60)})
    if not water_l:
        return {"target_main_water_l": 0, "estimated_main_seconds": 0, "doses": [],
                "phases": [{"name": "待命", "open_valves": "全部关闭", "target": "本次无灌水任务"}]}
    preflush_l = min(water_l, max(50, water_l * .15))
    postflush_l = min(max(0, water_l - preflush_l), max(100, water_l * .20))
    phases = [{"name": "预冲", "open_valves": "主水阀", "target": str(round(preflush_l, 1)) + " L"}]
    for index, dose in enumerate(doses):
        phases.append({"name": "注入 " + dose["valve"], "open_valves": "主水阀 + " + dose["valve"] + " 肥阀",
                       "target": str(dose["solution_l"]) + " L / 约 " + str(dose["estimated_seconds"]) + " 秒"})
        if index < len(doses) - 1:
            phases.append({"name": "罐间清水隔离", "open_valves": "主水阀", "target": "20 L"})
    phases.extend([{"name": "灌水与后冲", "open_valves": "主水阀", "target": "累计 " + str(round(water_l, 1)) + " L"},
                   {"name": "完成", "open_valves": "全部关闭", "target": "确认四阀关闭"}])
    return {"target_main_water_l": round(water_l, 1), "estimated_main_seconds": round(water_l / main_flow * 60),
            "doses": doses, "phases": phases,
            "interlocks": "主水无流量、肥路无流量或超流量、EC 超限、低液位或压力异常时，先关全部肥阀后关主水阀。"}


def decide(body):
    if not _state["loaded"] and not load_model():
        raise RuntimeError(_state["error"] or "模型未就绪")
    crop = str(body.get("crop", "玉米"))
    if crop not in _config["crops"]:
        raise ValueError("不支持的作物")
    day = date.fromisoformat(str(body.get("date", date.today().isoformat())))
    stage = str(body.get("stage") or _package["stage_for"](crop, day.timetuple().tm_yday) or "")
    if stage not in _config["crops"][crop]["stages"]:
        raise ValueError("请在该作物的生育期内选择有效日期或手动选择生育期")
    soil = next((x for x in _soils if x["name"] == body.get("soil_profile")), _soils[1])
    fc = number(body, "field_capacity", _package["estimate_fc"](soil), 10, 60)
    moisture20 = number(body, "moisture20", 20, 0, 100)
    # 单探针设备只上报 moisture20；缺少深层探针时明确沿用实测值。
    moisture = [moisture20, number(body, "moisture40", moisture20, 0, 100),
                number(body, "moisture60", moisture20, 0, 100)]
    ec = number(body, "soil_ec", 1.0, 0, 20)
    days = int(number(body, "days_since_fertigation", 8, 0, 365))
    levels = {key: str(body.get(key, "medium")) for key in ("soil_n_level", "soil_p_level", "soil_k_level")}
    if any(value not in {"low", "medium", "high"} for value in levels.values()):
        raise ValueError("土壤养分等级必须为 low、medium 或 high")
    weather_date = _weather.index[_weather.index.get_indexer([_package["pd"].Timestamp(day)], method="nearest")[0]]
    w = _weather.loc[weather_date]
    spec = _config["crops"][crop]["stages"][stage]
    weights = _package["np"].array([0.55, 0.30, 0.15] if spec["root_depth_m"] >= 0.6 else [0.7, 0.3, 0])
    root_m = float(_package["np"].dot(moisture, weights) / weights.sum())
    crop_cfg = _config["crops"][crop]
    factors = {"low": 1.0, "medium": 0.65, "high": 0.0}
    applied = {name: number(body, name, 0, 0, 100) for name in ("n_applied_stage", "p_applied_stage", "k_applied_stage")}
    row = {"crop": crop, "stage": stage, "soil_profile": soil["name"], "doy": day.timetuple().tm_yday,
           "t_mean": w.T2M, "t_max": w.T2M_MAX, "t_min": w.T2M_MIN, "rh": w.RH2M, "wind": w.WS2M,
           "radiation": w.ALLSKY_SFC_SW_DWN, "rain_today": w.PRECTOTCORR, "rain_next_2d": w.rain_next_2d,
           "eto": w.eto, "gdd10_14d": w.gdd10_14d, "rain_7d": w.rain_7d, "eto_7d": w.eto_7d, "dry_days": w.dry_days,
           "field_capacity": fc, "moisture20": moisture[0], "moisture40": moisture[1], "moisture60": moisture[2],
           "soil_ec": ec, "soil_ph": soil["ph"], "soc_g_kg": soil["soc_g_kg"], "soil_n_g_kg": soil["nitrogen_g_kg"],
           "sand_pct": soil["sand_pct"], "clay_pct": soil["clay_pct"], "bulk_density": soil["bulk_density"],
           "days_since_fertigation": days, **applied, "root_depth": spec["root_depth_m"], "root_moisture": root_m,
           "relative_fc": root_m / fc, "trigger_fc": spec["trigger_fc"], "target_fc": spec["target_fc"], "kc": spec["kc"],
           "n_remaining": max(0, crop_cfg["season_n_kg_mu"] * spec["n_share"] - applied["n_applied_stage"]),
           "p_remaining": max(0, crop_cfg["season_p2o5_kg_mu"] * spec["p_share"] - applied["p_applied_stage"]),
           "k_remaining": max(0, crop_cfg["season_k2o_kg_mu"] * spec["k_share"] - applied["k_applied_stage"]),
           "fertilizer_interval_ready": int(days >= 7), "ec_block": int(ec >= 2.0)}
    for short, level_key in (("n", "soil_n_level"), ("p", "soil_p_level"), ("k", "soil_k_level")):
        row[level_key] = levels[level_key]
        row[short + "_level_factor"] = factors[levels[level_key]]
    pred = _package["np"].maximum(0, _package["pipeline"].predict(_package["pd"].DataFrame([row])[_package["categorical"] + _package["numeric"]])[0])
    irrigate = root_m / fc <= spec["trigger_fc"] and w.rain_next_2d < max(5.0, spec["kc"] * w.eto)
    water = min(25, pred[0]) if irrigate and pred[0] >= 0.5 else 0
    fert = water > 0 and ec < 2 and days >= 7
    nutrients = [min(limit, pred[i]) if fert else 0 for i, limit in ((1, row["n_remaining"]), (2, row["p_remaining"]), (3, row["k_remaining"]))]
    for i, level_key in enumerate(("soil_n_level", "soil_p_level", "soil_k_level")):
        if levels[level_key] == "high": nutrients[i] = 0
    decision = {"crop": crop, "stage": stage, "soil_profile": soil["name"], "root_zone_moisture_pct": round(root_m, 1),
            "relative_field_capacity": round(root_m / fc, 3), "irrigate": water > 0,
            "irrigation_m3_mu": round(float(water), 1), "fertigate": any(x >= .05 for x in nutrients),
            "nitrogen_kg_mu": round(float(min(2.5, nutrients[0])), 2), "p2o5_kg_mu": round(float(min(1.5, nutrients[1])), 2),
            "k2o_kg_mu": round(float(min(3, nutrients[2])), 2), "weather_date": str(weather_date.date()),
            "warning": _package.get("metrics", {}).get("warning", "区域策略模型，使用前请结合田间实测复核。")}
    decision["job"] = build_job(body, decision)
    return decision


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass
    def send_json(self, code, value):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw))); self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.end_headers(); self.wfile.write(raw)
    def do_OPTIONS(self): self.send_json(204, {})
    def do_GET(self):
        if self.path.split("?", 1)[0].rstrip("/") in ("", "/health"):
            self.send_json(200, {**_state, "service": "zhirun-fertigation", "model": "hohhot_fertigation_policy_v2", "model_dir": MODEL_DIR, "crops": list(_config["crops"]) if _config else []})
        else: self.send_json(404, {"error": "not_found"})
    def do_POST(self):
        if self.path.split("?", 1)[0].rstrip("/") != "/predict": self.send_json(404, {"error": "not_found"}); return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self.send_json(200, {"ok": True, "decision": decide(body)})
        except Exception as exc: self.send_json(400, {"ok": False, "error": str(exc)})


if __name__ == "__main__":
    threading.Thread(target=load_model, daemon=True).start()
    print("智润水肥策略服务启动, 监听 0.0.0.0:%s" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
