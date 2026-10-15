import os
import glob
import math
from config.config import RECORDINGS_FOLDER, CLASSIFIER_FOLDER, REPLAYS_FOLDER, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from lib.srt import count_total_label_ms
from lib.stream_processing import CURRENT_VERSION


class AppState:
    """What the pages show, read off data/. Never writes, and reads once:
    a recording made while the app is open shows after a restart."""

    def __init__(self):
        self._model_cache = {}
        self._label_cache = {}
        self._checkpoint_times = {}
        self._replay_times = None
        self._duration_cache = {}

    def get_sound_labels(self):
        """Returns list of sound label directory names from data/recordings/."""
        labels = []
        if os.path.exists(RECORDINGS_FOLDER):
            for entry in sorted(os.listdir(RECORDINGS_FOLDER)):
                full_path = os.path.join(RECORDINGS_FOLDER, entry)
                if os.path.isdir(full_path):
                    labels.append(entry)
        return labels

    def get_recordings_for_label(self, label):
        """Returns list of dicts with wav_path and srt_path for a label."""
        recordings = []
        source_dir = os.path.join(RECORDINGS_FOLDER, label, "source")
        segments_dir = os.path.join(RECORDINGS_FOLDER, label, "segments")
        if not os.path.isdir(source_dir):
            return recordings

        wav_files = sorted([f for f in os.listdir(source_dir) if f.endswith(".wav")])
        for wav_file in wav_files:
            wav_path = os.path.join(source_dir, wav_file)
            base = wav_file.replace(".wav", "")
            srt_path = None
            if os.path.isdir(segments_dir):
                srt_candidates = [
                    os.path.join(segments_dir, base + ".MANUAL.srt"),
                    os.path.join(segments_dir, base + ".v" + str(CURRENT_VERSION) + ".srt"),
                ]
                for candidate in srt_candidates:
                    if os.path.exists(candidate):
                        srt_path = candidate
                        break
            recordings.append({"wav_path": wav_path, "srt_path": srt_path, "filename": wav_file})
        return recordings

    def get_label_duration_ms(self, label):
        """Total recorded ms for a label. Cached: this walks every .srt the
        label owns, and pages ask for the same numbers many times per refresh.
        """
        if label in self._duration_cache:
            return self._duration_cache[label]
        ms_per_frame = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)
        value = count_total_label_ms(
            label, os.path.join(RECORDINGS_FOLDER, label), ms_per_frame)
        self._duration_cache[label] = value
        return value

    def get_model_names(self):
        """Returns list of unique model base names (without .pkl extension)."""
        names = set()
        if os.path.exists(CLASSIFIER_FOLDER):
            for f in os.listdir(CLASSIFIER_FOLDER):
                if f.endswith(".pkl") and not f.endswith(".pth.tar"):
                    names.add(f.replace(".pkl", ""))
        return sorted(names)

    def get_model_metadata(self, model_name, load_weights=False):
        """Load model metadata. Fast by default (file sizes only).
        Set load_weights=True to also load labels/accuracy from pkl/pth.tar (slow).
        """
        cache_key = (model_name, load_weights)
        if cache_key in self._model_cache:
            meta = self._model_cache[cache_key]
            # Cheap, and a checkpoint read since the last call may have turned
            # up a better answer than the one cached here.
            meta["trained_at"], meta["trained_at_source"] = \
                self._trained_at(model_name)
            return meta

        pkl_path = os.path.join(CLASSIFIER_FOLDER, model_name + ".pkl")
        meta = {
            "name": model_name,
            "pkl_path": pkl_path,
            "labels": [],
            "net_count": 0,
            "nets": [],
            "best_accuracy": None,
            "total_size_bytes": 0,
            "pkl_exists": os.path.isfile(pkl_path),
            "weights_loaded": load_weights,
            "trained_at": None,
            "trained_at_source": None,
        }

        if meta["pkl_exists"]:
            meta["total_size_bytes"] += os.path.getsize(pkl_path)
            meta["trained_at"], meta["trained_at_source"] = \
                self._trained_at(model_name)

        best_files = sorted(glob.glob(pkl_path + "_*-BEST-weights.pth.tar"))
        meta["net_count"] = len(best_files)

        for bf in best_files:
            meta["total_size_bytes"] += os.path.getsize(bf)
            meta["nets"].append({"path": bf, "accuracy": None, "loss": None,
                                 "epoch": None, "label_accuracy": None,
                                 "combined_accuracy": None, "label_frames": None})

        all_weight_files = glob.glob(pkl_path + "_*-weights.pth.tar")
        for wf in all_weight_files:
            if wf not in best_files:
                meta["total_size_bytes"] += os.path.getsize(wf)

        if load_weights:
            # A checkpoint is ~3.8 MB against the pkl's ~38 MB, so read labels
            # here; joblib is the fallback for a model with no checkpoints
            # (one combined from other pkls).
            for net_info in meta["nets"]:
                try:
                    import torch
                    state = torch.load(net_info["path"], map_location="cpu", weights_only=False)
                    net_info["accuracy"] = state.get("accuracy")
                    net_info["loss"] = state.get("loss")
                    net_info["epoch"] = state.get("epoch")
                    # All None on anything trained before the fields existed.
                    net_info["label_accuracy"] = state.get("label_accuracy")
                    net_info["combined_accuracy"] = state.get("combined_accuracy")
                    net_info["label_frames"] = state.get("label_frames")
                    # One run made every net, so these describe the model
                    # rather than the net. First one to carry them wins.
                    if not meta.get("run_settings"):
                        meta["run_settings"] = state.get("run_settings") or {}
                    if not meta["labels"] and "labels" in state:
                        meta["labels"] = list(state["labels"])
                except Exception:
                    pass

            if not meta["labels"] and meta["pkl_exists"]:
                try:
                    import joblib
                    model = joblib.load(pkl_path)
                    if hasattr(model, "classes_"):
                        meta["labels"] = list(model.classes_)
                except Exception:
                    pass

            if meta["labels"]:
                self._label_cache[model_name] = meta["labels"]

            accuracies = [n["accuracy"] for n in meta["nets"] if n["accuracy"] is not None]
            if accuracies:
                meta["best_accuracy"] = max(accuracies)

        self._model_cache[cache_key] = meta
        return meta

    def get_model_trained_at(self, model_name):
        """When a model was trained. See _trained_at for where it comes from."""
        return self._trained_at(model_name)[0]

    def _trained_at(self, model_name):
        """(unix time, source) - most trustworthy source first.

        1. "checkpoint" - stamped inside the weights; survives copy and rename.
        2. "replay" - the replay CSV's filename timestamp; survives a copy but
           not a rename (the CSV is not renamed with the model).
        3. "mtime" - the pkl's file date; a copy or restore resets it, so
           callers must present it as uncertain.

        Only 3 is available without reading a checkpoint, so the list shows it
        first and improves it once the off-thread read lands.
        """
        stamped = self._checkpoint_times.get(model_name)
        if stamped:
            return stamped, "checkpoint"
        from_replay = self._training_run_times().get(model_name)
        if from_replay:
            return from_replay, "replay"
        pkl_path = os.path.join(CLASSIFIER_FOLDER, model_name + ".pkl")
        if os.path.isfile(pkl_path):
            return os.path.getmtime(pkl_path), "mtime"
        return None, None

    def model_sort_key(self, model_name):
        """Newest first, but mtime is only trusted to the day: a copied data
        dir stamps every pkl within the same second, so full precision would
        sort by copy order. Dates from a real training record keep theirs.
        """
        when, source = self._trained_at(model_name)
        when = when or 0
        if source == "mtime":
            when -= when % 86400
        return (-when, model_name)

    def get_model_facts(self, model_name):
        """Labels and training time from one BEST checkpoint - much cheaper
        than unpickling the pkl. Cached; [] labels means unreadable, so
        callers don't retry forever.
        """
        if model_name in self._label_cache:
            when, source = self._trained_at(model_name)
            return {"labels": self._label_cache[model_name],
                    "trained_at": when, "trained_at_source": source}

        pkl_path = os.path.join(CLASSIFIER_FOLDER, model_name + ".pkl")
        labels = []
        best_files = sorted(glob.glob(pkl_path + "_*-BEST-weights.pth.tar"))
        if best_files:
            try:
                import torch
                state = torch.load(best_files[0], map_location="cpu",
                                   weights_only=False)
                labels = list(state.get("labels") or [])
                # Absent from every model trained before the field existed.
                if state.get("trained_at"):
                    self._checkpoint_times[model_name] = state["trained_at"]
            except Exception:
                labels = []
        if not labels:
            # No checkpoints, or unreadable ones: a combined model keeps its
            # classes only inside the pkl.
            labels = self.get_model_metadata(model_name,
                                             load_weights=True)["labels"]

        self._label_cache[model_name] = labels
        when, source = self._trained_at(model_name)
        return {"labels": labels, "trained_at": when,
                "trained_at_source": source}

    def get_all_model_details(self):
        """Returns list of metadata dicts for all models."""
        return [self.get_model_metadata(name) for name in self.get_model_names()]

    def _training_run_times(self):
        """model name -> unix time of its most recent training run, from the
        replay CSV filenames. The filename timestamp is the one training-time
        record that survives a copy or a restore, which reset the pkl's mtime.
        """
        if self._replay_times is not None:
            return self._replay_times

        times = {}
        if os.path.isdir(REPLAYS_FOLDER):
            for f in os.listdir(REPLAYS_FOLDER):
                if not (f.startswith("model_training_") and f.endswith(".csv")):
                    continue
                stem = f[len("model_training_"):-len(".csv")]
                name, sep, stamp = stem.rpartition(".pkl")
                if not sep or not stamp.isdigit():
                    continue
                when = int(stamp)
                if when > times.get(name, 0):
                    times[name] = when
        self._replay_times = times
        return times
