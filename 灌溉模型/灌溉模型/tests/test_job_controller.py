import unittest

from scripts.build_job import HARDWARE, build_job
from scripts.controller import FlowController, SensorFrame, State
from scripts.recommend import recommend


def dry_potato_decision():
    return recommend("马铃薯", "块茎膨大", [18, 21], 28, 0, 5.5, 8, 1.0, 0, 0, 0, "low", "low", "low")


class JobTests(unittest.TestCase):
    def test_npk_job_created(self):
        job = build_job(1.0, dry_potato_decision())
        self.assertGreater(job["target_main_water_l"], 0)
        self.assertEqual([d["valve"] for d in job["doses"]], ["A", "B", "C"])
        for phase in job["phases"]:
            self.assertLessEqual(len(set(phase["open_valves"]) & {"A", "B", "C"}), 1)

    def test_no_irrigation_means_no_dose(self):
        decision = recommend("玉米", "抽雄吐丝", [25, 25, 25], 28, 20, 5.0, 8)
        job = build_job(2.0, decision)
        self.assertEqual(job["target_main_water_l"], 0)
        self.assertEqual(job["doses"], [])

    def test_main_no_flow_fault(self):
        job = build_job(1.0, dry_potato_decision())
        c = FlowController(job, HARDWARE)
        f = SensorFrame(0, 0, {"A": 0, "B": 0, "C": 0}, {"A": 0, "B": 0, "C": 0})
        c.start_with_baseline(f)
        out = c.update(f)
        self.assertEqual(c.state, State.FAULT)
        self.assertFalse(any(out.as_dict().values()))

    def test_dose_no_flow_fault(self):
        job = build_job(0.01, dry_potato_decision())
        c = FlowController(job, HARDWARE)
        f = SensorFrame(0, 60, {"A": 0, "B": 0, "C": 0}, {"A": 0, "B": 0, "C": 0})
        c.start_with_baseline(f)
        # 小面积预冲洗下限被总水量限制，第一帧推进到A，下一帧检查肥路。
        c.update(SensorFrame(job["phases"][0]["main_water_target_l"], 60,
                             {"A": 0, "B": 0, "C": 0}, {"A": 0, "B": 0, "C": 0}))
        c.update(SensorFrame(job["phases"][0]["main_water_target_l"] + 1, 60,
                             {"A": 0, "B": 0, "C": 0}, {"A": 0, "B": 0, "C": 0}))
        self.assertEqual(c.state, State.FAULT)


if __name__ == "__main__":
    unittest.main()
