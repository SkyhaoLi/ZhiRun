import io
import os
import sys
import unittest
import zipfile
from unittest.mock import patch
from xml.etree import ElementTree


SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import zhirun_server as server


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.latest = server._latest_by_device
        self.recordings = server._recordings_by_device
        self.saved_latest = dict(self.latest)
        self.saved_recordings = dict(self.recordings)
        self.latest.clear()
        self.recordings.clear()

    def tearDown(self):
        self.latest.clear()
        self.latest.update(self.saved_latest)
        self.recordings.clear()
        self.recordings.update(self.saved_recordings)

    def test_samples_immediately_and_then_every_five_minutes(self):
        self.latest["device-1"] = {"_ts": 1000, "airTemp": 21.5}
        with patch.object(server, "now", return_value=1000):
            status = server.start_recording("device-1")

        self.assertTrue(status["active"])
        self.assertEqual(status["sample_count"], 1)
        self.assertEqual(status["next_sample_at"], 1300)

        server.maybe_record_sample("device-1", {"_ts": 1299, "airTemp": 22.0}, 1299)
        self.assertEqual(server.recording_snapshot("device-1")["sample_count"], 1)

        server.maybe_record_sample("device-1", {"_ts": 1300, "airTemp": 22.1}, 1300)
        status = server.recording_snapshot("device-1")
        self.assertEqual(status["sample_count"], 2)
        self.assertEqual(status["next_sample_at"], 1600)

    def test_builds_valid_xlsx_archive(self):
        recording = {
            "items": [{"_recorded_at": 1000, "_data_ts": 998, "airTemp": 21.5, "soilMoist": 48.0}]
        }
        payload = server.recording_xlsx("device-1", recording)

        with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
            self.assertEqual(workbook.testzip(), None)
            self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())
            sheet = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))

        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = sheet.findall(".//x:sheetData/x:row", namespace)
        self.assertEqual(len(rows), 2)
        text = "".join(node.text or "" for node in sheet.findall(".//x:t", namespace))
        self.assertIn("记录时间", text)
        self.assertIn("空气温度 (°C)", text)


if __name__ == "__main__":
    unittest.main()
