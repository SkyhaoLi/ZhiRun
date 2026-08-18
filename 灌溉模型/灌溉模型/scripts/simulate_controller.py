"""无需硬件的四阀工作单仿真。"""

from __future__ import annotations

import json
from pathlib import Path

from build_job import HARDWARE, build_job
from controller import FlowController, SensorFrame, State
from recommend import recommend


decision = recommend("马铃薯", "块茎膨大", [18, 21], 28, 0, 5.5, 8, 1.0, 0, 0, 0, "low", "low", "low")
job = build_job(1.0, decision)
controller = FlowController(job, HARDWARE)
main_total = 0.0
dose_total = {"A": 0.0, "B": 0.0, "C": 0.0}
frame = SensorFrame(main_total, 60.0, dose_total.copy(), {"A": 1.0, "B": 1.0, "C": 1.0}, 1.5)
outputs = controller.start_with_baseline(frame)
events = []
for second in range(40000):
    if outputs.water:
        main_total += 1.0
    for valve in "ABC":
        if outputs.as_dict()[valve]:
            dose_total[valve] += 1.0 / 60.0
    frame = SensorFrame(main_total, 60.0 if outputs.water else 0.0, dose_total.copy(),
                        {v: (1.0 if outputs.as_dict()[v] else 0.0) for v in "ABC"}, 1.5)
    old = controller.state
    outputs = controller.update(frame)
    if controller.state != old:
        events.append({"second": second + 1, "state": controller.state.value,
                       "main_l": round(main_total, 1), "dose_l": {k: round(v, 3) for k, v in dose_total.items()}})
    if controller.state in {State.COMPLETE, State.FAULT}:
        break
print(json.dumps({"decision": decision, "job": job, "events": events, "final_state": controller.state.value,
                  "fault": controller.fault, "main_l": main_total, "dose_l": dose_total}, ensure_ascii=False, indent=2))
