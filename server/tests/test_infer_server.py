import unittest

from server import infer_server


class CaptureProvider:
    def __init__(self):
        self.sensor_data = None

    def fetch(self, _latitude, _longitude, sensor_data=None, offline=False):
        self.sensor_data = sensor_data
        return sensor_data


class SoilFrameValidationTests(unittest.TestCase):
    def test_complete_zero_soil_frame_is_invalid(self):
        self.assertTrue(infer_server.invalid_zero_soil_frame({
            "soilMoist": 0, "soilEc": 0, "n": 0, "p": 0, "k": 0,
        }))

    def test_partial_or_nonzero_frame_is_not_invalid(self):
        self.assertFalse(infer_server.invalid_zero_soil_frame({"soilMoist": 0, "soilEc": 0}))
        self.assertFalse(infer_server.invalid_zero_soil_frame({
            "soilMoist": 12.5, "soilEc": 0, "n": 0, "p": 0, "k": 0,
        }))

    def test_invalid_frame_keeps_temperature_and_omits_soil_measurements(self):
        original_provider, original_defaults = infer_server._provider, infer_server._defaults
        provider = CaptureProvider()
        infer_server._provider, infer_server._defaults = provider, (40.84, 111.75)
        try:
            infer_server.environment_from_request({
                "soilMoist": 0, "soilTemp": 22.9, "soilEc": 0, "soilPH": 9,
                "n": 0, "p": 0, "k": 0,
            }, "玉米")
        finally:
            infer_server._provider, infer_server._defaults = original_provider, original_defaults
        self.assertEqual(provider.sensor_data["soil_temperature_c"], 22.9)
        for key in ("soil_moisture_20_pct", "soil_ec_ds_m", "soil_ph",
                    "soil_n_mg_kg", "soil_p_mg_kg", "soil_k_mg_kg"):
            self.assertNotIn(key, provider.sensor_data)
        self.assertEqual(provider.sensor_data["source"]["soil_sensor"],
                         "invalid_zero_frame; regional prior applied")


if __name__ == "__main__":
    unittest.main()
