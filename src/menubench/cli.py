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
    dataset: Annotated[str | None, typer.Option(help="Override the dataset directory, e.g. data/real.")] = None,
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
    updates = {k: v for k, v in {"limit": limit, "split": split, "dataset": dataset}.items() if v is not None}
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
def report(split: Annotated[str, typer.Option(help="Which split's runs go into the tables.")] = "test") -> None:
    """Build README tables and the risk-coverage chart from the latest evaluated run of every config."""
    from menubench.report import write_reports

    for path in write_reports(split=split):
        typer.echo(f"wrote {path}")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Reload on code changes (development).")] = False,
) -> None:
    """Start the web app (API + built frontend)."""
    import uvicorn

    uvicorn.run("menubench.server.app:create_app", factory=True, host=host, port=port, reload=reload)


@app.command()
def openapi(out: Annotated[Path, typer.Option(help="Where to write the schema.")] = Path("web/openapi.json")) -> None:
    """Export the OpenAPI schema; the frontend generates its TypeScript types from it."""
    import json

    from menubench.server.app import create_app

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(create_app().openapi(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command()
def calibrate(
    run_dir: Annotated[Path, typer.Argument(help="A run on the dev split with a pipeline that records signals.")],
    out: Annotated[Path, typer.Option(help="Where to write the calibrator.")] = Path("configs/calibration/full.json"),
) -> None:
    """Fit confidence calibration and auto-place thresholds on a dev run."""
    from menubench.calibration import expected_calibration_error, fit, labelled
    from menubench.runs import RunDir

    run = RunDir(run_dir)
    if run.info().split != "dev":
        typer.echo("Refusing to calibrate on a non-dev split: thresholds must not see the test data.", err=True)
        raise typer.Exit(code=2)
    samples = labelled(run)
    calibrator = fit(samples, fitted_on=run.run_id)
    labels = [ok for _, ok in samples]
    before = expected_calibration_error([p.confidence for p, _ in samples], labels)["ece"]
    after = expected_calibration_error([calibrator.predict(p.signals) for p, _ in samples], labels)["ece"]
    calibrator.save(out)
    typer.echo(f"samples {calibrator.samples}, correct {calibrator.positives}")
    typer.echo(f"ECE on dev: {before} -> {after} (in-sample)")
    typer.echo("auto-place thresholds: " + ", ".join(f"risk<={k}: {v}" for k, v in calibrator.thresholds.items()))
    typer.echo(
        "weights: " + ", ".join(f"{f}={c:+.2f}" for f, c in zip(calibrator.features, calibrator.coef, strict=True))
    )
    typer.echo(f"wrote {out}")


@app.command()
def gallery(
    run_dir: Annotated[Path, typer.Argument(help="A finished run whose menus become demo examples.")],
    menus: Annotated[str, typer.Option(help="Comma-separated menu ids.")],
    out: Annotated[Path, typer.Option(help="Gallery folder shipped with the server.")] = Path(
        "src/menubench/server/gallery"
    ),
) -> None:
    """Copy precomputed results into the demo gallery, so the demo works without spending anything."""
    from datetime import UTC, datetime

    from PIL import Image

    from menubench.data import Dataset
    from menubench.runs import RunDir
    from menubench.server.try_api import GalleryItem, TryJob, TryPage

    run = RunDir(run_dir)
    dataset = Dataset(Path(run.info().dataset))
    predictions = {p.menu_id: p for p in run.predictions()}
    out.mkdir(parents=True, exist_ok=True)
    for menu_id in [m.strip() for m in menus.split(",") if m.strip()]:
        ann = dataset.annotation(menu_id)
        image = f"{menu_id}.jpg"
        with Image.open(dataset.page_path(ann, 0)) as img:
            img.convert("RGB").save(out / image, format="JPEG", quality=85)
        page = ann.pages[0]
        job = TryJob(
            job_id=menu_id,
            status="done",
            pages=[TryPage(index=0, width=page.width, height=page.height, url=f"/api/try/gallery/{image}")],
            prediction=predictions[menu_id].model_copy(update={"lines": ()}),
            created_at=datetime.now(UTC),
        )
        title = f"{ann.template} · {ann.lang} · {ann.augment.value if ann.augment else 'clean'}"
        note = (
            "synthetic test menu; layout held out during development"
            if ann.template in ("price_left", "tv_landscape")
            else "synthetic test menu"
        )
        item = GalleryItem(id=menu_id, title=title, note=note, job=job)
        (out / f"{menu_id}.json").write_text(item.model_dump_json(indent=1), encoding="utf-8")
        typer.echo(f"added {menu_id}")
