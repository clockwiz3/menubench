"""Command line entry point. Commands are wired up milestone by milestone (see PLAN.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from menubench import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False, help="MenuBench: menu price extraction benchmark.")


def _not_ready(milestone: str) -> None:
    typer.echo(f"Not implemented yet (planned for {milestone}, see PLAN.md).", err=True)
    raise typer.Exit(code=2)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def synth(
    out: Annotated[Path, typer.Option(help="Output dataset directory.")] = Path("data/synth"),
    n: Annotated[int, typer.Option("-n", help="Number of menus.")] = 50,
    seed: Annotated[int, typer.Option(help="Generator seed.")] = 42,
) -> None:
    """Generate synthetic menus with exact ground truth."""
    from menubench.synth.generate import SynthConfig, generate_dataset

    with typer.progressbar(length=n, label="Rendering") as bar:
        count = generate_dataset(out, SynthConfig(n=n, seed=seed), on_menu=lambda _: bar.update(1))
    typer.echo(f"{count} menus written to {out}")


@app.command()
def run(
    config: Annotated[Path, typer.Argument(help="Run config (YAML).")],
    limit: Annotated[int | None, typer.Option(help="Process only the first N menus.")] = None,
    split: Annotated[str | None, typer.Option(help="Override the dataset split.")] = None,
    mode: Annotated[str, typer.Option(help="Cache mode: record-missing | replay | live.")] = "record-missing",
    dry_run: Annotated[bool, typer.Option(help="Estimate cost without calling models.")] = False,
) -> None:
    """Run a pipeline configuration over a dataset split, then score it."""
    import asyncio
    import json

    from menubench.eval import evaluate_run
    from menubench.eval.report import format_summary
    from menubench.llm import CacheMode
    from menubench.pipeline.runner import RunConfig, estimate_cost, run_config

    cfg = RunConfig.load(config)
    updates = {k: v for k, v in {"limit": limit, "split": split}.items() if v is not None}
    cfg = cfg.model_copy(update=updates)
    if dry_run:
        typer.echo(json.dumps(estimate_cost(cfg), indent=1))
        return
    from menubench.data import Dataset

    total = len(Dataset(Path(cfg.dataset)).ids(cfg.split, cfg.limit))
    with typer.progressbar(length=total, label=cfg.name) as bar:
        run_dir = asyncio.run(run_config(cfg, mode=CacheMode(mode), on_menu=lambda _: bar.update(1)))
    typer.echo(format_summary(evaluate_run(run_dir)))
    typer.echo(f"run dir    {run_dir.path}")


@app.command("eval")
def evaluate(
    run_dir: Annotated[Path, typer.Argument(help="Directory produced by `menubench run`.")],
) -> None:
    """Score predictions against ground truth."""
    from menubench.eval import evaluate_run
    from menubench.eval.report import format_summary
    from menubench.runs import RunDir

    typer.echo(format_summary(evaluate_run(RunDir(run_dir))))


@app.command()
def report() -> None:
    """Build README tables from the latest evaluated run of every config."""
    from menubench.report import write_reports

    for path in write_reports():
        typer.echo(f"wrote {path}")
