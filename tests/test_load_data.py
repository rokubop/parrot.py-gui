import os
import shutil
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


class TestSampleDataFromLabel(unittest.TestCase):
    """AudioDataset reads augmented[i] as the augmented copy of data[i]."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        label_dir = os.path.join(self.dir, "pop")
        os.makedirs(os.path.join(label_dir, "source"))
        os.makedirs(os.path.join(label_dir, "segments"))
        shutil.copy(os.path.join(FIXTURES, "recordings", "pop", "source", "pop.wav"),
                    os.path.join(label_dir, "source", "pop.wav"))
        from config.config import CURRENT_VERSION
        shutil.copy(os.path.join(FIXTURES, "segmentation", "pop.srt"),
                    os.path.join(label_dir, "segments", f"pop.v{CURRENT_VERSION}.srt"))
        self.grouped = {"pop": [label_dir]}

    def tearDown(self):
        shutil.rmtree(self.dir)

    def sample(self):
        from config.config import TYPE_FEATURE_ENGINEERING_NORM_MFSC
        from lib.load_data import generate_data_balance_strategy_map, sample_data_from_label
        strategies = generate_data_balance_strategy_map(self.grouped, "all", True)
        return sample_data_from_label("pop", self.grouped, strategies,
                                      TYPE_FEATURE_ENGINEERING_NORM_MFSC, "all")

    def test_every_sample_has_an_augmented_copy(self):
        data = self.sample()
        self.assertTrue(data["label"])
        self.assertTrue(data["background"])
        self.assertEqual(len(data["augmented"]), len(data["label"]))
        self.assertEqual(len(data["background_augmented"]), len(data["background"]))

    def test_background_copies_are_augmented(self):
        data = self.sample()
        plain = np.array([x[1] for x in data["background"]])
        augmented = np.array([x[1] for x in data["background_augmented"]])
        self.assertEqual(augmented.shape, plain.shape)
        self.assertFalse(np.allclose(plain, augmented))


if __name__ == "__main__":
    unittest.main()
