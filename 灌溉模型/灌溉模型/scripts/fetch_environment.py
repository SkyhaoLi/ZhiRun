"""按农田坐标获取实时预报与SoilGrids静态土壤先验。"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def get_json(base: str, params: dict) -> dict:
    url = base + "?" + urllib.parse.urlencode(params, doseq=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.load(response)


def fetch(latitude: float, longitude: float) -> dict:
    forecast = get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": latitude, "longitude": longitude, "timezone": "Asia/Shanghai", "forecast_days": 7,
        "daily": "et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min",
    })
    soil = get_json("https://rest.isric.org/soilgrids/v2.0/properties/query", {
        "lat": latitude, "lon": longitude,
        "property": ["phh2o", "soc", "nitrogen", "clay", "sand", "silt", "bdod", "cec"],
        "depth": ["0-5cm", "5-15cm", "15-30cm", "30-60cm"], "value": "mean",
    })
    layers = {}
    for layer in soil["properties"]["layers"]:
        factor = layer["unit_measure"]["d_factor"]
        layers[layer["name"]] = {d["label"]: (None if d["values"]["mean"] is None else d["values"]["mean"] / factor)
                                  for d in layer["depths"]}
    return {
        "location": {"latitude": latitude, "longitude": longitude},
        "forecast": forecast["daily"],
        "soilgrids": layers,
        "sources": {
            "forecast": "Open-Meteo (FAO ET0 and weather forecast)",
            "soil": "ISRIC SoilGrids 2.0, 250 m prediction; must be replaced/corrected by field laboratory tests",
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--latitude", type=float, required=True)
    p.add_argument("--longitude", type=float, required=True)
    args = p.parse_args()
    payload = fetch(args.latitude, args.longitude)
    out = ROOT / "data" / "environment"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"field_{args.latitude:.5f}_{args.longitude:.5f}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存 {path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
