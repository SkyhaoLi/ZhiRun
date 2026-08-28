"""下载呼和浩特 NASA POWER 逐日气象，供后续本地 ET0/需水模型使用。"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="20150101")
    p.add_argument("--end", default="20251231")
    args = p.parse_args()
    params = {
        "parameters": "T2M,T2M_MAX,T2M_MIN,RH2M,WS2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN",
        "community": "AG",
        "longitude": 111.75,
        "latitude": 40.84,
        "start": args.start,
        "end": args.end,
        "format": "JSON",
    }
    url = "https://power.larc.nasa.gov/api/temporal/daily/point?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = json.load(response)
    values = payload["properties"]["parameter"]
    frame = pd.DataFrame(values)
    frame.index = pd.to_datetime(frame.index, format="%Y%m%d")
    frame.index.name = "date"
    out = ROOT / "data" / "weather"
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / "hohhot_nasa_power_daily.csv", encoding="utf-8-sig")
    meta = {"source": "NASA POWER Daily API", "url": url, "latitude": 40.84, "longitude": 111.75,
            "start": args.start, "end": args.end, "rows": len(frame)}
    (out / "source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

