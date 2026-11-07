import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import joblib
import torch
from lib import models
from lib.audio_model import AudioModel
from lib.dummy_classifier import DummyClassifier

AUDIO_SETTINGS = {"version": 1, "RATE": 16000, "CHANNELS": 1, "RECORD_SECONDS": 1,
                  "SLIDING_WINDOW_AMOUNT": 2, "FEATURE_ENGINEERING_TYPE": 1}


class ModelsFolder(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.models_dir = os.path.join(self.dir, "models")
        self.replays_dir = os.path.join(self.dir, "replays")
        os.makedirs(self.models_dir)
        os.makedirs(self.replays_dir)
        for name, path in (("CLASSIFIER_FOLDER", self.models_dir),
                           ("REPLAYS_FOLDER", self.replays_dir)):
            patch = mock.patch.object(models, name, path)
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def touch(self, folder, filename):
        path = os.path.join(folder, filename)
        open(path, "w").close()
        return path

    def save_model(self, name):
        path = os.path.join(self.models_dir, name + ".pkl")
        joblib.dump(AudioModel(AUDIO_SETTINGS, DummyClassifier()), path)
        return path

    # The fields lib/audio_net.py saves after each epoch
    def save_checkpoint(self, filename, **fields):
        checkpoint = {"state_dict": {"fc1.weight": torch.zeros(2, 2)}, "input_size": 120,
                      "labels": ["pop", "silence"], "accuracy": 0.9, "last_row": [],
                      "loss": 0.1, "epoch": 3, "random_seed": 1,
                      "label_accuracy": [0.9, 0.9], "combined_accuracy": 0.9,
                      "label_frames": [10, 10], "trained_at": 1786747776, "run_settings": {}}
        checkpoint.update(fields)
        path = os.path.join(self.models_dir, filename)
        torch.save(checkpoint, path)
        return path


class TestGetModelNames(ModelsFolder):

    def test_pkls_in_order(self):
        self.touch(self.models_dir, "pop.pkl")
        self.touch(self.models_dir, "click.pkl")
        self.touch(self.models_dir, "pop.pkl_1-BEST-weights.pth.tar")
        self.touch(self.models_dir, "notes.txt")
        self.assertEqual(models.get_model_names(), ["click", "pop"])

    def test_no_models_folder(self):
        shutil.rmtree(self.models_dir)
        self.assertEqual(models.get_model_names(), [])


class TestGetModelFiles(ModelsFolder):

    def test_pkl_then_its_checkpoints(self):
        pkl = self.touch(self.models_dir, "pop.pkl")
        best = self.touch(self.models_dir, "pop.pkl_1-BEST-weights.pth.tar")
        last = self.touch(self.models_dir, "pop.pkl_1-weights.pth.tar")
        self.touch(self.models_dir, "pop2.pkl")
        self.touch(self.models_dir, "pop2.pkl_1-BEST-weights.pth.tar")
        self.assertEqual(models.get_model_files("pop"), [pkl, best, last])

    def test_no_files(self):
        self.assertEqual(models.get_model_files("pop"), [])


class TestGetBestCheckpointPaths(ModelsFolder):

    def test_one_per_net(self):
        self.touch(self.models_dir, "pop.pkl")
        best_1 = self.touch(self.models_dir, "pop.pkl_1-BEST-weights.pth.tar")
        best_2 = self.touch(self.models_dir, "pop.pkl_2-BEST-weights.pth.tar")
        self.touch(self.models_dir, "pop.pkl_1-weights.pth.tar")
        self.assertEqual(models.get_best_checkpoint_paths("pop"), [best_1, best_2])

    def test_combined_model_has_none(self):
        self.touch(self.models_dir, "pop.pkl")
        self.assertEqual(models.get_best_checkpoint_paths("pop"), [])


class TestReadCheckpoint(ModelsFolder):

    def test_fields_without_weights(self):
        checkpoint = models.read_checkpoint(self.save_checkpoint("pop.pkl_1-BEST-weights.pth.tar"))
        self.assertEqual(checkpoint["labels"], ["pop", "silence"])
        self.assertEqual(checkpoint["epoch"], 3)
        self.assertEqual(checkpoint["trained_at"], 1786747776)
        self.assertNotIn("state_dict", checkpoint)

    def test_damaged(self):
        path = os.path.join(self.models_dir, "pop.pkl_1-BEST-weights.pth.tar")
        with open(path, "wb") as f:
            f.write(b"not a checkpoint")
        self.assertIsNone(models.read_checkpoint(path))


class TestReadModelLabels(ModelsFolder):

    def test_labels_from_pkl(self):
        self.save_model("pop")
        self.assertEqual(models.read_model_labels("pop"), ["silence", "noise"])

    def test_missing(self):
        self.assertEqual(models.read_model_labels("pop"), [])


class TestGetTrainingRunTimes(ModelsFolder):

    def test_newest_run_per_model(self):
        # "pkl1000" lists before "pkl900"
        self.touch(self.replays_dir, "model_training_pop.pkl1000.csv")
        self.touch(self.replays_dir, "model_training_pop.pkl900.csv")
        self.touch(self.replays_dir, "model_training_click.pkl200.csv")
        self.touch(self.replays_dir, "replay_400.csv")
        self.touch(self.replays_dir, "run.csv")
        self.assertEqual(models.get_training_run_times(), {"pop": 1000, "click": 200})

    def test_no_replays_folder(self):
        shutil.rmtree(self.replays_dir)
        self.assertEqual(models.get_training_run_times(), {})


class TestGetTrainedAt(ModelsFolder):

    def test_checkpoint_first(self):
        self.touch(self.models_dir, "pop.pkl")
        self.assertEqual(models.get_trained_at("pop", {"trained_at": 500}, {"pop": 300}),
                         (500, "checkpoint"))

    def test_then_training_run(self):
        self.touch(self.models_dir, "pop.pkl")
        self.touch(self.replays_dir, "model_training_pop.pkl300.csv")
        self.assertEqual(models.get_trained_at("pop"), (300, "replay"))

    def test_then_pkl_mtime(self):
        os.utime(self.touch(self.models_dir, "pop.pkl"), (200, 200))
        self.assertEqual(models.get_trained_at("pop"), (200, "mtime"))

    def test_no_model(self):
        self.assertEqual(models.get_trained_at("pop"), (None, None))


class TestGetNewestFirstKey(ModelsFolder):

    def test_newest_first(self):
        trained_at = {"old": (100, "checkpoint"), "new": (200, "checkpoint")}
        self.assertEqual(sorted(trained_at, key=lambda name: models.get_newest_first_key(name, trained_at[name])),
                         ["new", "old"])

    def test_mtime_counts_to_the_day(self):
        day = 86400 * 20000
        trained_at = {"b": (day + 5, "mtime"), "a": (day + 9, "mtime"), "c": (day + 1, "checkpoint")}
        self.assertEqual(sorted(trained_at, key=lambda name: models.get_newest_first_key(name, trained_at[name])),
                         ["c", "a", "b"])


if __name__ == "__main__":
    unittest.main()
