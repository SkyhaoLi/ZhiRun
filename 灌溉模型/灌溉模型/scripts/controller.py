"""Controller for three independently metered dosing pumps and one outlet pump."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    IDLE = "IDLE"
    DOSING = "DOSING"
    OUTLET = "OUTLET_TRANSFER"
    COMPLETE = "COMPLETE"
    FAULT = "FAULT"


@dataclass
class SensorFrame:
    main_total_l: float = 0.0
    main_flow_l_min: float = 0.0
    dose_total_l: dict[str, float] = field(default_factory=dict)
    dose_flow_l_min: dict[str, float] = field(default_factory=dict)
    ec_ds_m: float | None = None
    timestamp_s: float | None = None
    pressure_bar: float | None = None
    tank_levels_pct: dict[str, float] | None = None
    emergency_stop: bool = False


@dataclass
class Outputs:
    n_pump: bool = False
    p_pump: bool = False
    k_pump: bool = False
    outlet_pump: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {"N_PUMP": self.n_pump, "P_PUMP": self.p_pump,
                "K_PUMP": self.k_pump, "OUTLET_PUMP": self.outlet_pump}


@dataclass
class FlowController:
    job: dict
    hardware: dict
    state: State = State.IDLE
    fault: str | None = None
    delivered: dict[str, float] = field(default_factory=dict)
    baseline: dict[str, float] = field(default_factory=dict)
    elapsed_s: float = 0.0
    last_timestamp_s: float | None = None

    def _fail(self, message: str) -> Outputs:
        self.state, self.fault = State.FAULT, message
        return Outputs()

    def _advance_time(self, frame: SensorFrame) -> None:
        if frame.timestamp_s is not None and self.last_timestamp_s is not None:
            self.elapsed_s += max(0.0, frame.timestamp_s - self.last_timestamp_s)
        else:
            self.elapsed_s += 1.0
        if frame.timestamp_s is not None:
            self.last_timestamp_s = frame.timestamp_s

    def _dosing_outputs(self, frame: SensorFrame) -> Outputs:
        active = {}
        targets = self.job.get("targets_l", {})
        line_map = {"N": "A", "P": "B", "K": "C"}
        for element, line_id in line_map.items():
            total = float(frame.dose_total_l.get(line_id, frame.dose_total_l.get(element, 0.0)))
            self.delivered[element] = max(0.0, total - self.baseline.get(element, 0.0))
            active[element] = self.delivered[element] < float(targets.get(element, 0.0))
            if active[element]:
                flow = float(frame.dose_flow_l_min.get(line_id, frame.dose_flow_l_min.get(element, 0.0)))
                limits = self.hardware["fertilizer_lines"][line_id]
                if flow < float(limits["minimum_flow_l_min"]) or flow > float(limits["maximum_flow_l_min"]):
                    return self._fail("%s fertilizer flow out of range" % element)
        if not any(active.values()):
            self.state = State.OUTLET if self.job.get("outlet_run_s", 0) else State.COMPLETE
            self.elapsed_s = 0.0
            return Outputs(outlet_pump=self.state == State.OUTLET)
        return Outputs(active["N"], active["P"], active["K"], False)

    def start(self, frame: SensorFrame) -> Outputs:
        if frame.emergency_stop:
            return self._fail("emergency stop active")
        self.fault = None
        self.baseline = {
            element: float(frame.dose_total_l.get(line_id, frame.dose_total_l.get(element, 0.0)))
            for element, line_id in {"N": "A", "P": "B", "K": "C"}.items()
        }
        self.delivered = {"N": 0.0, "P": 0.0, "K": 0.0}
        self.elapsed_s = 0.0
        self.last_timestamp_s = frame.timestamp_s
        self.state = State.DOSING if any(float(v) > 0 for v in self.job.get("targets_l", {}).values()) else State.OUTLET
        if self.state == State.OUTLET and not self.job.get("outlet_run_s", 0):
            self.state = State.COMPLETE
            return Outputs()
        return self._dosing_outputs(frame) if self.state == State.DOSING else Outputs(outlet_pump=True)

    def start_with_baseline(self, frame: SensorFrame) -> Outputs:
        return self.start(frame)

    def update(self, frame: SensorFrame) -> Outputs:
        if self.state in {State.IDLE, State.COMPLETE, State.FAULT}:
            return Outputs()
        if frame.emergency_stop:
            return self._fail("emergency stop active")
        self._advance_time(frame)
        if self.state == State.DOSING:
            maximum = float(self.hardware.get("control", {}).get("maximum_dose_runtime_s", 1800))
            if self.elapsed_s > maximum:
                return self._fail("fertilizer dosing timeout")
            return self._dosing_outputs(frame)
        if self.elapsed_s >= float(self.job.get("outlet_run_s", 0)):
            self.state = State.COMPLETE
            return Outputs()
        return Outputs(outlet_pump=True)
