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
dose_total = {"N": 0.0, "P": 0.0, "K": 0.0}
frame = SensorFrame(
    main_total_l=main_total,
    main_flow_l_min=0.0,
    dose_total_l=dose_total.copy(),
    dose_flow_l_min={"N": 1.0, "P": 1.0, "K": 1.0},
    ec_ds_m=1.5,
    timestamp_s=0.0,
)
outputs = controller.start_with_baseline(frame)
events = []
for second in range(40000):
    if outputs.outlet_pump:
        main_total += 1.0
    pump_state = {"N": outputs.n_pump, "P": outputs.p_pump, "K": outputs.k_pump}
    for element, is_on in pump_state.items():
        if is_on:
            dose_total[element] += 1.0 / 60.0
    frame = SensorFrame(
        main_total_l=main_total,
        main_flow_l_min=60.0 if outputs.outlet_pump else 0.0,
        dose_total_l=dose_total.copy(),
        dose_flow_l_min={element: (1.0 if is_on else 0.0) for element, is_on in pump_state.items()},
        ec_ds_m=1.5,
        timestamp_s=float(second + 1),
    )
    old = controller.state
    outputs = controller.update(frame)
    if controller.state != old:
        events.append({"second": second + 1, "state": controller.state.value,
                       "main_l": round(main_total, 1), "dose_l": {k: round(v, 3) for k, v in dose_total.items()}})
    if controller.state in {State.COMPLETE, State.FAULT}:
        break
print(json.dumps({"decision": decision, "job": job, "events": events, "final_state": controller.state.value,
                  "fault": controller.fault, "main_l": main_total, "dose_l": dose_total}, ensure_ascii=False, indent=2))
