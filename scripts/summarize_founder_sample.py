"""Retain and summarize the owner-approved bounded founder-rating sample."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pydantic import TypeAdapter

from sim_pilot.analysis.evaluation import FounderSampleRating
from sim_pilot.private_files import atomic_write_private_text

RATINGS = TypeAdapter(list[FounderSampleRating])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=5)
    arguments = parser.parse_args()
    ratings = RATINGS.validate_json(arguments.source.read_text(encoding="utf-8"), strict=True)
    if arguments.count <= 0 or arguments.count > len(ratings):
        raise RuntimeError("sample count must select at least one available rating")
    sample = tuple(ratings[: arguments.count])
    if len({item.case_id for item in sample}) != len(sample):
        raise RuntimeError("sample rating IDs must be unique")
    arguments.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_write_private_text(
        arguments.output / "founder-sample-review.json",
        "[\n" + ",\n".join(item.model_dump_json(indent=2) for item in sample) + "\n]",
    )
    metrics = {
        "schema_version": 1,
        "sample_size": len(sample),
        "sample_scope": "first company-health subset",
        "not_full_catalog_rating": True,
        "manual_rating": dict(Counter(item.manual_rating for item in sample)),
        "revealed_nonobvious_information": dict(
            Counter(item.revealed_nonobvious_information for item in sample)
        ),
        "would_use_during_gameplay": dict(
            Counter(item.would_use_during_gameplay for item in sample)
        ),
        "too_verbose": dict(Counter(item.too_verbose for item in sample)),
        "correct_or_acceptable_rate": sum(
            item.manual_rating in {"correct", "acceptable"} for item in sample
        )
        / len(sample),
        "revealed_yes_or_partially_rate": sum(
            item.revealed_nonobvious_information in {"yes", "partially"} for item in sample
        )
        / len(sample),
        "would_use_yes_or_maybe_rate": sum(
            item.would_use_during_gameplay in {"yes", "maybe"} for item in sample
        )
        / len(sample),
        "too_verbose_rate": sum(item.too_verbose == "yes" for item in sample) / len(sample),
    }
    atomic_write_private_text(
        arguments.output / "founder-sample-metrics.json",
        json.dumps(metrics, indent=2) + "\n",
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
