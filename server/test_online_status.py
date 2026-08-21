import os
import sys
import unittest
from unittest.mock import patch


SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import zhirun_server as server


class OnlineStatusTests(unittest.TestCase):
    def setUp(self):
        self.saved_devices = dict(server._devices)
        self.saved_latest = dict(server._latest_by_device)
        server._devices.clear()
        server._latest_by_device.clear()
        server._devices['atlas-1'] = {'device_name': 'Atlas', 'source': 'atlas'}

    def tearDown(self):
        server._devices.clear()
        server._devices.update(self.saved_devices)
        server._latest_by_device.clear()
        server._latest_by_device.update(self.saved_latest)

    def test_config_uses_shared_online_timeout(self):
        server._latest_by_device['atlas-1'] = {'_ts': 1000}

        with patch.object(server, 'now', return_value=1000 + server.DEVICE_ONLINE_TIMEOUT):
            config = server.config_snapshot('atlas-1')
        self.assertEqual(config['mode'], 'normal')
        self.assertEqual(config['online_timeout_s'], server.DEVICE_ONLINE_TIMEOUT)

        with patch.object(server, 'now', return_value=1001 + server.DEVICE_ONLINE_TIMEOUT):
            config = server.config_snapshot('atlas-1')
        self.assertEqual(config['mode'], 'offline')

    def test_empty_config_still_publishes_timeout(self):
        config = server.config_snapshot(None)
        self.assertEqual(config['mode'], 'offline')
        self.assertEqual(config['online_timeout_s'], server.DEVICE_ONLINE_TIMEOUT)


if __name__ == '__main__':
    unittest.main()
