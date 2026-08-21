import json
import tempfile
import unittest
from pathlib import Path

import atlas200i_collector as collector


class H3cNetworkTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config = dict(collector.DEFAULTS)
        self.config.update({
            "ZHIRUN_H3C_STATE_FILE": str(Path(self.temporary.name) / "h3c.json"),
            "ZHIRUN_H3C_UPLINK_SSID": "SkyhaoLi",
            "ZHIRUN_H3C_LOCAL_WIFI_PASSWORD": "local-password",
        })
        self.controller = collector.ValveController(self.config)

    def tearDown(self):
        self.temporary.cleanup()

    def test_scan_uses_best_result_per_ssid_and_band(self):
        self.controller._h3c_request = lambda *_args, **_kwargs: {
            "code": 0,
            "data1": {"neighbourList": [
                {"ssid": "Field", "radio": "5G", "auth": "wpa2psk", "rssi": -70, "bssid": "a"},
                {"ssid": "Field", "radio": "5G", "auth": "wpa2psk", "rssi": -45, "bssid": "b"},
            ]},
            "data2": {"neighbourList": [
                {"ssid": "SkyhaoLi", "radio": "2.4G", "auth": "wpa2psk", "rssi": -50, "bssid": "c"},
            ]},
        }

        self.controller._scan_wifi()

        self.assertEqual(2, len(self.controller.wifi_networks))
        self.assertEqual(-45, self.controller.wifi_networks[0]["rssi"])
        self.assertEqual("2.4G", self.controller.h3c_uplink["radio"])
        self.assertEqual("", self.controller.wifi_error)

    def test_connect_uses_scan_metadata_without_persisting_passwords(self):
        requests = []
        self.controller.wifi_networks = [{
            "ssid": "Field", "radio": "5G", "auth": "wpa2psk", "bssid": "aa", "rssi": -40,
        }]

        def request(path, payload, timeout=12):
            requests.append((path, payload, timeout))
            if path.endswith("getssidname"):
                return {"code": 0, "data": {"ssid": "H3C_LOCAL", "ssid5g": "H3C_LOCAL_5G"}}
            return {"code": "0", "message": "COMMON:Success"}

        self.controller._h3c_request = request
        self.controller._connect_wifi("Field", "upstream-password")

        setup = requests[-1][1]
        self.assertEqual("5G", setup["repeaterConfig"]["periorradio"])
        self.assertEqual("upstream-password", setup["repeaterConfig"]["periorkey"])
        self.assertEqual("H3C_LOCAL", setup["wirelessConfig"]["ssid"])
        saved = json.loads(Path(self.config["ZHIRUN_H3C_STATE_FILE"]).read_text(encoding="utf-8"))
        self.assertNotIn("password", json.dumps(saved).lower())
        self.assertNotIn("upstream-password", json.dumps(saved))
        self.assertEqual("", self.controller.wifi_error)


if __name__ == "__main__":
    unittest.main()
