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
    dry_run: Annotated[bool, typer.Option(help="Estimate cost without calling models.")] = False,
) -> None:
    """Run a pipeline configuration over a dataset split."""
    _not_ready("M3")


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
    """Build README tables and charts from finished runs."""
    _not_ready("M8")
