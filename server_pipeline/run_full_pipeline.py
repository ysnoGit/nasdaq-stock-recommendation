from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PipelineStep:
    name: str
    group: str
    script: Path | None
    requires_wrds: bool = False
    enabled: bool = True
    todo: str | None = None


PIPELINE_STEPS = [
    PipelineStep(
        name="Extract Compustat annual and quarterly fundamentals",
        group="extraction",
        script=Path("server_pipeline/fundamentals/extract_compustat_fundamentals_s3.py"),
        requires_wrds=True,
    ),
    PipelineStep(
        name="Extract recent Compustat daily security data",
        group="extraction",
        script=Path("server_pipeline/daily/extract_compustat_daily_incremental_s3.py"),
        requires_wrds=True,
    ),
    PipelineStep(
        name="Build fundamental growth history",
        group="transform",
        script=Path("server_pipeline/fundamentals/build_fundamental_growth_history_s3.py"),
    ),
    PipelineStep(
        name="Build incremental daily market metrics",
        group="transform",
        script=Path("server_pipeline/daily/build_daily_market_metrics_s3.py"),
    ),
    PipelineStep(
        name="Build incremental weekly market metrics",
        group="transform",
        script=Path("server_pipeline/daily/build_weekly_market_metrics_s3.py"),
    ),
    PipelineStep(
        name="Build recent daily volume metrics",
        group="transform",
        script=Path("server_pipeline/daily/build_recent_daily_volume_metrics_s3.py"),
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the EC2 S3-backed NASDAQ stock recommendation pipeline."
    )
    parser.add_argument(
        "--skip-wrds",
        action="store_true",
        help="Skip WRDS extraction steps and run only non-WRDS steps.",
    )
    parser.add_argument(
        "--only",
        choices=["extraction", "transform"],
        help="Run only one pipeline group.",
    )
    return parser.parse_args()


def selected_steps(args: argparse.Namespace) -> list[PipelineStep]:
    steps = PIPELINE_STEPS

    if args.only:
        steps = [step for step in steps if step.group == args.only]

    if args.skip_wrds:
        steps = [step for step in steps if not step.requires_wrds]

    return steps


def validate_script_exists(step: PipelineStep) -> Path:
    if step.script is None:
        raise RuntimeError(f"{step.name} has no runnable script yet.")

    script_path = REPO_ROOT / step.script
    if not script_path.exists():
        raise RuntimeError(f"Pipeline script does not exist: {script_path}")

    return script_path


def run_step(step: PipelineStep) -> None:
    print("\n" + "=" * 80)
    print(step.name)
    print("=" * 80)

    if not step.enabled:
        print(step.todo or "TODO: this pipeline step is not enabled yet.")
        return

    script_path = validate_script_exists(step)
    subprocess.run(
        [sys.executable, str(script_path)],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> None:
    args = parse_args()
    steps = selected_steps(args)

    if not steps:
        raise RuntimeError("No pipeline steps selected.")

    print(f"Repository root: {REPO_ROOT}")
    print("Selected steps:")
    for step in steps:
        status = "ready" if step.enabled else "todo"
        print(f"  [{status}] {step.group}: {step.name}")

    try:
        for step in steps:
            run_step(step)
    except subprocess.CalledProcessError as exc:
        print("\nPipeline failed.")
        print(f"Failed command: {' '.join(exc.cmd)}")
        print(f"Exit code: {exc.returncode}")
        raise

    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()
