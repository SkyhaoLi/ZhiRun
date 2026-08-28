import unittest

from scripts.build_job import HARDWARE
from scripts.controller import FlowController, SensorFrame, State
from scripts.fertigation_model import EnvironmentInput, FertigationModel, dynamic_irrigation_threshold
from scripts.recommend import CONFIG


def dry_environment() -> EnvironmentInput:
    return EnvironmentInput(
        latitude=40.84,
        longitude=111.75,
        observation_time="2026-07-20",
        air_temperature_c=25,
        air_humidity_pct=45,
        soil_moisture_20_pct=10,
        soil_moisture_40_pct=12,
        soil_moisture_60_pct=14,
        soil_temperature_c=22,
        soil_n_mg_kg=800,
        soil_p_mg_kg=10,
        soil_k_mg_kg=80,
        wind_speed_m_s=2,
        light_lux=30000,
        rain_24h_mm=0,
        rain_forecast_mm=0,
        rain_next_2d_mm=0,
        eto_forecast_mm=5.5,
        soil_ph=8.0,
        soil_ec_ds_m=1.0,
    )


class FertigationModelTests(unittest.TestCase):
    def test_only_manual_fields_are_concentrations_and_are_used_for_dose_volume(self):
        result = FertigationModel(use_ml=False).plan(200, 100, 50, dry_environment())
        self.assertTrue(result["job"]["doses"])
        by_pump = {item["pump"]: item for item in result["job"]["doses"]}
        self.assertEqual(by_pump["N_PUMP"]["concentration_g_l"], 200)
        self.assertEqual(by_pump["P_PUMP"]["concentration_g_l"], 100)
        self.assertEqual(by_pump["K_PUMP"]["concentration_g_l"], 50)
        self.assertEqual(set(result["hardware"]["flow_meters"]), {"N", "P", "K"})
        mapped = FertigationModel(use_ml=False).plan({"N": 200, "P": 100, "K": 50}, dry_environment())
        self.assertEqual(mapped["manual_inputs"]["N_g_L"], 200.0)

    def test_independent_meters_and_outlet_output(self):
        result = FertigationModel(use_ml=False).plan(100, 80, 120, dry_environment())
        job = result["job"]
        controller = FlowController(job, HARDWARE)
        frame = SensorFrame(dose_total_l={"A": 0, "B": 0, "C": 0},
                            dose_flow_l_min={"A": 1, "B": 1, "C": 1})
        outputs = controller.start(frame)
        self.assertTrue(outputs.n_pump and outputs.p_pump and outputs.k_pump)
        targets = job["targets_l"]
        outputs = controller.update(SensorFrame(
            dose_total_l={"A": targets["N"], "B": targets["P"], "C": targets["K"]},
            dose_flow_l_min={"A": 0, "B": 0, "C": 0},
        ))
        self.assertEqual(controller.state, State.OUTLET)
        self.assertTrue(outputs.outlet_pump)

    def test_chinese_sensor_mapping_and_ph_interlock(self):
        env = EnvironmentInput.from_mapping({
            "纬度": 40.84, "经度": 111.75, "空气温度": 25, "空气湿度": 40,
            "CO2浓度": 420, "土壤湿度": [10, 12, 14], "土壤温度": 22,
            "土壤氮浓度": 800, "土壤磷浓度": 10, "土壤钾浓度": 80,
            "风速": 2, "光照强度": 30000, "24h雨量": 0, "土壤pH": 9.0,
            "rain_next_2d_mm": 0, "eto_forecast_mm": 5.5, "observation_time": "2026-07-20",
        })
        result = FertigationModel(use_ml=False).plan(100, 80, 120, env)
        self.assertTrue(result["decision"]["irrigate"])
        self.assertFalse(result["decision"]["fertigate"])
        self.assertTrue(any("pH" in alert for alert in result["decision"]["alerts"]))

    def test_hot_forecast_raises_trigger_and_is_used_for_decision(self):
        moderate = dry_environment()
        moderate.soil_moisture_20_pct = 17.5
        moderate.soil_moisture_40_pct = 17.5
        moderate.soil_moisture_60_pct = 17.5
        hot = EnvironmentInput.from_mapping({**moderate.as_dict(), "weather_forecast": [
            {"tmax_c": 36, "tmin_c": 25, "rain_mm": 0, "eto_mm": 8, "humidity_pct": 35,
             "wind_speed_m_s": 4, "light_lux": 50000},
            {"tmax_c": 34, "tmin_c": 24, "rain_mm": 0, "eto_mm": 7, "humidity_pct": 38,
             "wind_speed_m_s": 4, "light_lux": 48000},
        ]})
        stage_cfg = CONFIG["crops"]["玉米"]["stages"]["抽雄吐丝"]
        base = dynamic_irrigation_threshold(stage_cfg, moderate)
        adjusted = dynamic_irrigation_threshold(stage_cfg, hot)
        self.assertGreater(adjusted["dynamic_trigger_fc"], base["dynamic_trigger_fc"])
        result = FertigationModel(use_ml=False).plan(100, 80, 120, hot)
        self.assertEqual(result["automatic_inputs"]["forecast_summary"]["temperature_max_c"], 36.0)
        self.assertEqual(result["model_features"]["t_max"], 36.0)
        self.assertEqual(result["decision"]["dynamic_trigger_relative_fc"], adjusted["dynamic_trigger_fc"])


if __name__ == "__main__":
    unittest.main()
