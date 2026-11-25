import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from gui.services import user_config


class TestWriteUserConfig(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "code", "config.py")
        patch = mock.patch.object(user_config, "USER_CONFIG_PATH", self.path)
        patch.start()
        self.addCleanup(patch.stop)

    def lines(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read().splitlines()

    def test_saving_again_writes_each_key_once(self):
        user_config.write_user_config({"OUTPUT_DEVICE_INDEX": 20, "SOMETHING_ELSE": 1})
        user_config.write_user_config({"INPUT_DEVICE_INDEX": 12})
        user_config.write_user_config({"OUTPUT_DEVICE_INDEX": 21})
        self.assertEqual(sorted(self.lines()), ["INPUT_DEVICE_INDEX = 12",
                                                "OUTPUT_DEVICE_INDEX = 21",
                                                "SOMETHING_ELSE = 1"])

    def test_copies_already_there_collapse_to_the_last(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("SOMETHING_ELSE = 1\nOUTPUT_DEVICE_INDEX = 20\n"
                    "SOMETHING_ELSE = 2\nOUTPUT_DEVICE_INDEX = 20\nimport os\n")
        user_config.write_user_config({"INPUT_DEVICE_INDEX": 12})
        self.assertEqual(self.lines(), ["SOMETHING_ELSE = 2", "import os",
                                        "INPUT_DEVICE_INDEX = 12", "OUTPUT_DEVICE_INDEX = 20"])


if __name__ == "__main__":
    unittest.main()
