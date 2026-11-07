"""Trained models: their files, checkpoints and when they were trained."""
import os
import re
from config.config import CLASSIFIER_FOLDER, REPLAYS_FOLDER

def get_model_path(name):
    return os.path.join(CLASSIFIER_FOLDER, name + ".pkl")

# Example: -> ["bronze", "pops_and_clicks"]
def get_model_names():
    if not os.path.isdir(CLASSIFIER_FOLDER):
        return []
    return sorted(f[:-len(".pkl")] for f in os.listdir(CLASSIFIER_FOLDER)
                  if f.endswith(".pkl") and not f.startswith("."))

# The pkl, then every checkpoint training wrote for it. Matched whole, since
# "pop.pkl_2" is a valid name for another model.
# Example: "pop" -> ["data/models/pop.pkl",
#                    "data/models/pop.pkl_1-BEST-weights.pth.tar",
#                    "data/models/pop.pkl_1-weights.pth.tar"]
def get_model_files(name):
    files = []
    if os.path.isfile(get_model_path(name)):
        files.append(get_model_path(name))
    if os.path.isdir(CLASSIFIER_FOLDER):
        checkpoint = re.compile(re.escape(name) + r"\.pkl_\d+(-BEST)?-weights\.pth\.tar")
        files += [os.path.join(CLASSIFIER_FOLDER, f) for f in sorted(os.listdir(CLASSIFIER_FOLDER))
                  if checkpoint.fullmatch(f)]
    return files

# One per net, holding its best epoch. Only torch training writes them, so a
# combined, random forest or MLP model has none.
def get_best_checkpoint_paths(name):
    return [path for path in get_model_files(name) if path.endswith("-BEST-weights.pth.tar")]

# What training saved with the net, without the weights themselves.
# Example: -> {"labels": ["pop", "silence"], "accuracy": 0.97, "epoch": 41,
#              "trained_at": 1786747776, ...}
def read_checkpoint(path):
    import torch
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    except Exception:
        # A checkpoint is a pickle, so a damaged one can raise anything
        return None
    if not isinstance(checkpoint, dict):
        return None
    checkpoint.pop("state_dict", None)
    return checkpoint

# Unpickles the whole model: slow, and the only source for a model without checkpoints.
def read_model_labels(name):
    import joblib
    try:
        model = joblib.load(get_model_path(name))
    except Exception:
        return []
    return list(getattr(model, "classes_", []))

# Newest training run per model, from the replay csv names.
# Example: "model_training_pop.pkl1786747776.csv" -> {"pop": 1786747776}
def get_training_run_times():
    times = {}
    if not os.path.isdir(REPLAYS_FOLDER):
        return times
    for filename in os.listdir(REPLAYS_FOLDER):
        if not (filename.startswith("model_training_") and filename.endswith(".csv")):
            continue
        name, pkl, stamp = filename[len("model_training_"):-len(".csv")].rpartition(".pkl")
        if pkl and stamp.isdigit():
            times[name] = max(times.get(name, 0), int(stamp))
    return times

# (unix time, source), most trustworthy source first: a checkpoint survives a
# copy and a rename, a training run's replay csv survives a copy, the pkl's
# mtime survives neither. Pass read_checkpoint() of a best checkpoint to use it.
# Example: "pop" -> (1786747776, "checkpoint")
def get_trained_at(name, checkpoint=None, run_times=None):
    if checkpoint and checkpoint.get("trained_at"):
        return checkpoint["trained_at"], "checkpoint"
    if run_times is None:
        run_times = get_training_run_times()
    if name in run_times:
        return run_times[name], "replay"
    if os.path.isfile(get_model_path(name)):
        return os.path.getmtime(get_model_path(name)), "mtime"
    return None, None

# Sorts newest first. Copying a data folder gives every pkl the same mtime to
# the second, so an mtime counts only to the (UTC) day, or the order is copy order.
def get_newest_first_key(name, trained_at):
    when, source = trained_at
    when = when or 0
    if source == "mtime":
        when -= when % 86400
    return (-when, name)
