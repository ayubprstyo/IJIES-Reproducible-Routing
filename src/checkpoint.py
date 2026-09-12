"""
src/checkpoint.py — generic checkpoint/resume utilities.

Every long-running computation in this repository (calibration sweeps,
the 51-date experiment, fuzzy evaluation, Liu-ALNS held-out runs) uses
these helpers so that:
  - partial progress is written to disk incrementally (never held only in
    memory until the very end);
  - a re-run of the same cell/notebook skips combinations already present
    in the checkpoint file, keyed on an explicit, caller-provided tuple of
    columns (e.g. date + trigger + shock + seed + method);
  - no duplicate rows are ever appended.
"""
import os
import pandas as pd


def load_done_keys(checkpoint_path, key_columns):
    """Return the set of already-completed key tuples, or an empty set if
    the checkpoint file does not exist yet."""
    if not os.path.exists(checkpoint_path):
        return set()
    df = pd.read_csv(checkpoint_path)
    missing = [c for c in key_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Checkpoint file {checkpoint_path} is missing key columns: {missing}")
    return set(zip(*[df[c] for c in key_columns]))


def append_rows(checkpoint_path, rows):
    """Append a list-of-dicts to the checkpoint CSV, writing a header only
    if the file does not yet exist. No deduplication is performed here --
    callers must use load_done_keys() beforehand to avoid recomputing (and
    therefore re-appending) an already-completed combination."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    file_exists = os.path.exists(checkpoint_path)
    os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
    df.to_csv(checkpoint_path, mode='a', header=not file_exists, index=False)


def assert_no_duplicates(checkpoint_path, key_columns):
    """Hard integrity check: raise if any key tuple appears more than once."""
    df = pd.read_csv(checkpoint_path)
    dup_counts = df.groupby(key_columns).size()
    duplicated = dup_counts[dup_counts > 1]
    if len(duplicated) > 0:
        raise AssertionError(
            f"Checkpoint integrity failure in {checkpoint_path}: "
            f"{len(duplicated)} duplicate key combinations found, e.g. {duplicated.index[:5].tolist()}")
    return True


def assert_completeness(checkpoint_path, expected_keys, key_columns):
    """Hard integrity check: raise if any expected key tuple is missing."""
    done = load_done_keys(checkpoint_path, key_columns)
    missing = expected_keys - done
    if missing:
        raise AssertionError(
            f"Checkpoint completeness failure in {checkpoint_path}: "
            f"{len(missing)} expected combinations missing, e.g. {list(missing)[:5]}")
    return True
