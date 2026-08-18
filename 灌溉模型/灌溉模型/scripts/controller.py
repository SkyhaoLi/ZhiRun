"""四阀流量闭环控制状态机；GPIO层由实际ESP32/PLC适配器实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    IDLE = "IDLE"
    PREFLUSH = "PREFLUSH"
    DOSE = "DOSE"
    INTER_TANK_FLUSH = "INTER_TANK_FLUSH"
    POSTFLUSH = "IRRIGATE_AND_POSTFLUSH"
    COMPLETE = "COMPLETE"
    FAULT = "FAULT"


@dataclass
class SensorFrame:
    main_total_l: float
    main_flow_l_min: float
    dose_total_l: dict[str, float]
    dose_flow_l_min: dict[str, float]
    ec_ds_m: float | None = None


@dataclass
class Outputs:
    water: bool = False
    a: bool = False
    b: bool = False
    c: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {"WATER": self.water, "A": self.a, "B": self.b, "C": self.c}


@dataclass
class FlowController:
    job: dict
    hardware: dict
    state: State = State.IDLE
    phase_index: int = 0
    phase_start_main_l: float = 0.0
    dose_start_l: dict[str, float] = field(default_factory=dict)
    fault: str | None = None

    def _outputs_for_phase(self) -> Outputs:
        phase_name = self.job["phases"][self.phase_index]["state"]
        if phase_name.startswith("DOSE_"):
            return Outputs(water=True, **{phase_name[-1].lower(): True})
        if phase_name in {"PREFLUSH", "INTER_TANK_FLUSH", "IRRIGATE_AND_POSTFLUSH"}:
            return Outputs(water=True)
        return Outputs()

    def start(self, frame: SensorFrame) -> Outputs:
        if self.job["target_main_water_l"] <= 0:
            self.state = State.COMPLETE
            return Outputs()
        self.phase_index = 0
        self.phase_start_main_l = frame.main_total_l
        self.dose_start_l = dict(frame.dose_total_l)
        self.state = State.PREFLUSH
        return Outputs(water=True)

    def _fail(self, message: str) -> Outputs:
        self.state, self.fault = State.FAULT, message
        return Outputs()

    def update(self, frame: SensorFrame) -> Outputs:
        if self.state in {State.IDLE, State.COMPLETE, State.FAULT}:
            return Outputs()
        main = self.hardware["main"]
        if frame.main_flow_l_min < main["minimum_flow_l_min"] or frame.main_flow_l_min > main["maximum_flow_l_min"]:
            return self._fail("主水流量越界")
        if frame.ec_ds_m is not None and frame.ec_ds_m > self.hardware["control"]["maximum_injection_ec_ds_m"]:
            return self._fail("主管EC超过注肥安全上限")
        phase = self.job["phases"][self.phase_index]
        phase_name = phase["state"]
        if phase_name == "PREFLUSH":
            if frame.main_total_l - self.phase_start_main_l >= phase["main_water_target_l"]:
                self.phase_index += 1
                self.phase_start_main_l = frame.main_total_l
                return self._outputs_for_phase()
            else:
                return Outputs(water=True)
        if phase_name.startswith("DOSE_"):
            valve = phase_name[-1]
            limits = self.hardware["fertilizer_lines"][valve]
            delivered = frame.dose_total_l.get(valve, 0) - self.dose_start_l.get(valve, 0)
            if delivered >= phase["target_solution_l"]:
                self.phase_index += 1
                self.phase_start_main_l = frame.main_total_l
                return self._outputs_for_phase()
            flow = frame.dose_flow_l_min.get(valve, 0)
            if flow < limits["minimum_flow_l_min"] or flow > limits["maximum_flow_l_min"]:
                return self._fail(f"肥路{valve}流量越界")
            return Outputs(water=True, **{valve.lower(): True})
        if phase_name == "INTER_TANK_FLUSH":
            if frame.main_total_l - self.phase_start_main_l >= phase["main_water_target_l"]:
                self.phase_index += 1
                self.phase_start_main_l = frame.main_total_l
                return self._outputs_for_phase()
            return Outputs(water=True)
        if phase_name == "IRRIGATE_AND_POSTFLUSH":
            job_used = frame.main_total_l - getattr(self, "job_start_main_l", self.phase_start_main_l)
            if job_used >= self.job["target_main_water_l"]:
                self.state = State.COMPLETE
                return Outputs()
            return Outputs(water=True)
        self.state = State.COMPLETE
        return Outputs()

    def start_with_baseline(self, frame: SensorFrame) -> Outputs:
        self.job_start_main_l = frame.main_total_l
        return self.start(frame)
