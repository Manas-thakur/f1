from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot matched physical race experiments")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before, after = json.loads(args.before.read_text()), json.loads(args.after.read_text())
    fig, axes = plt.subplots(4, 2, figsize=(13, 10), sharex=True, layout="constrained")
    for column, case in enumerate(("pass", "abort")):
        for runs, label, color in ((before, "Original", "#ab3d34"), (after, "Revised", "#147b70")):
            run = next(run for run in runs if run["case"] == case and run["seed"] == 11)
            rows = [row for row in run["rows"] if row["t"] <= 8]
            t = [row["t"] for row in rows]
            for index, key in enumerate(("gap", "relative_speed", "accel", "lateral")):
                axes[index, column].plot(
                    t, [row[key] for row in rows], label=label, color=color, linewidth=1.5
                )
                axes[index, column].grid(alpha=0.2)
            if label == "Revised":
                previous = ""
                for row in rows:
                    if row["state"] != previous and row["state"] in {
                        "committed",
                        "alongside",
                        "returning",
                        "aborting",
                    }:
                        axes[3, column].axvline(row["t"], color="#555555", alpha=0.25)
                        axes[3, column].annotate(
                            row["state"],
                            (row["t"], row["lateral"]),
                            xytext=(3, 8),
                            textcoords="offset points",
                            fontsize=8,
                            rotation=35,
                        )
                    previous = row["state"]
        axes[0, column].set_title("Closing on a steady rival" if case == "pass" else "Rival accelerates away")
        axes[0, column].axhline(0, color="#222222", linewidth=0.7)
        axes[0, column].legend(loc="lower left")
        axes[3, column].set_xlabel("Simulated time (s)")
    for axis, label in zip(
        axes[:, 0],
        (
            "Rival minus follower progress (m)",
            "Follower closing speed (m/s)",
            "Follower acceleration (m/s²)",
            "Follower lateral position (m)",
        ),
        strict=True,
    ):
        axis.set_ylabel(label)
    fig.suptitle(
        "Physical racecraft: completed pass and aborted attempt\n"
        "Matched cars, initial states, delay and seed; first 8 s of 15 s runs",
        fontsize=16,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
