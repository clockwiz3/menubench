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
    features: Annotated[str | None, typer.Option(help="Comma-separated subset of signals (ablations).")] = None,
) -> None:
    """Fit confidence calibration and auto-place thresholds on a dev run."""
    from menubench.calibration import expected_calibration_error, fit, labelled
    from menubench.runs import RunDir

    run = RunDir(run_dir)
    if run.info().split != "dev":
        typer.echo("Refusing to calibrate on a non-dev split: thresholds must not see the test data.", err=True)
        raise typer.Exit(code=2)
    samples = labelled(run)
    only = [f.strip() for f in features.split(",")] if features else None
    calibrator = fit(samples, fitted_on=run.run_id, only=only)
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


real = typer.Typer(no_args_is_help=True, help="The real-photo dataset: splits and annotation self-agreement.")
app.add_typer(real, name="real")


@real.command("split")
def real_split(
    dev: Annotated[int, typer.Option(help="How many finished menus go to real-dev; the rest is real-test.")] = 20,
    seed: Annotated[int, typer.Option(help="Shuffle seed, recorded so the split can be reproduced.")] = 7,
    force: Annotated[bool, typer.Option(help="Reshuffle an existing split (only if you mean it).")] = False,
    root: Annotated[Path, typer.Option(help="Dataset folder.")] = Path("data/real"),
) -> None:
    """Fix the dev/test split once. Test menus then stay untouched until the pipeline is frozen."""
    from collections import Counter

    from menubench.data.real import RealStore, SplitError, assign_splits

    try:
        result = assign_splits(RealStore(root), dev=dev, seed=seed, force=force)
    except SplitError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(", ".join(f"{k}: {v}" for k, v in sorted(Counter(result.values()).items())) + f" (seed {seed})")


@real.command("import")
def real_import(
    root: Annotated[Path, typer.Option(help="Dataset folder with loose images dropped into it.")] = Path("data/real"),
    groups: Annotated[Path | None, typer.Option(help="Venue groups, pins, tags and exclusions (YAML).")] = None,
    lang: Annotated[str, typer.Option(help="Language for files without a group.")] = "sr",
) -> None:
    """Turn loose images in the dataset folder into menus for Annotate, one image per menu."""
    import yaml

    from menubench.data.real import RealStore, import_folder

    groups = groups or root / "groups.yaml"
    config = yaml.safe_load(groups.read_text(encoding="utf-8")) if groups.exists() else {}
    report = import_folder(RealStore(root), config, default_lang=lang)
    for kind, rows in report.items():
        if rows:
            typer.echo(f"{kind}: {len(rows)}")
            for row in rows:
                typer.echo(f"  {row}")


@real.command("prelabel")
def real_prelabel(
    root: Annotated[Path, typer.Option(help="Dataset folder.")] = Path("data/real"),
    config: Annotated[Path, typer.Option(help="Pipeline used for the proposals.")] = Path("configs/demo.yaml"),
    dry_run: Annotated[bool, typer.Option(help="Only list the menus that would be pre-labelled.")] = False,
    redo: Annotated[
        bool, typer.Option(help="Also redo pre-labelled drafts nobody has saved since, e.g. after a pipeline fix.")
    ] = False,
) -> None:
    """Pre-label every menu that has not been touched yet (status: new), so Annotate opens with proposals."""
    import asyncio

    from menubench.data.real import RealStore, Status
    from menubench.server.annotate_api import prelabel_menu

    store = RealStore(root)
    todo = [
        m
        for m in store.ids()
        if store.meta(m).split != "recheck"
        and (store.meta(m).status is Status.NEW or (redo and store.meta(m).untouched_since_prelabel()))
    ]
    typer.echo(f"{len(todo)} menus to pre-label (~$0.006 each)")
    if dry_run:
        return

    async def run() -> None:
        sem = asyncio.Semaphore(3)

        async def one(menu_id: str) -> None:
            async with sem:
                try:
                    await prelabel_menu(store, menu_id, config)
                    prices = len(store.annotation(menu_id).prices)
                    typer.echo(f"  {menu_id} ({store.meta(menu_id).group}): {prices} prices")
                except Exception as exc:  # one bad photo must not stop the batch
                    typer.echo(f"  {menu_id}: failed: {type(exc).__name__}: {exc}"[:200], err=True)

        await asyncio.gather(*(one(m) for m in todo))

    asyncio.run(run())


@real.command("recheck")
def real_recheck(
    menus: Annotated[str, typer.Argument(help="Comma-separated menu ids to label again, blind.")],
    root: Annotated[Path, typer.Option(help="Dataset folder.")] = Path("data/real"),
) -> None:
    """Create empty copies of finished menus for blind re-annotation (do it a week later)."""
    from menubench.data.real import RealStore, SplitError, create_recheck

    store = RealStore(root)
    for menu_id in [m.strip() for m in menus.split(",") if m.strip()]:
        try:
            copy_id = create_recheck(store, menu_id)
            typer.echo(f"created {copy_id}: label it in Annotate without looking at the original")
        except (SplitError, KeyError) as exc:
            typer.echo(f"{menu_id}: {exc}", err=True)


@real.command("agreement")
def real_agreement(
    root: Annotated[Path, typer.Option(help="Dataset folder.")] = Path("data/real"),
    out: Annotated[Path, typer.Option(help="Report file.")] = Path("reports/annotation_agreement.md"),
) -> None:
    """Score each blind recheck against the first labelling and write the self-agreement report."""
    from menubench.data.real import RealStore
    from menubench.eval.agreement import self_agreement

    result = self_agreement(RealStore(root))
    if not result["menus"]:
        typer.echo("No finished rechecks yet.", err=True)
        raise typer.Exit(code=2)
    lines = [
        f"Annotation self-agreement on {result['menus']} menus, {result['prices']} prices, labelled twice blind:",
        "",
        f"- same price, same item: **{result['pair_agreement'] * 100:.1f}%**",
        f"- same price (value and position): {result['price_agreement'] * 100:.1f}%",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    out.write_text(text + "\n", encoding="utf-8")
    typer.echo(text)


@real.command("export")
def real_export(
    root: Annotated[Path, typer.Option(help="Dataset folder.")] = Path("data/real"),
    out: Annotated[Path, typer.Option(help="Release folder, ready to upload to Hugging Face.")] = Path("release"),
    card: Annotated[Path, typer.Option(help="Dataset card copied in as README.md.")] = Path("hf/README.md"),
    draft: Annotated[
        bool, typer.Option(help="Allow an unfixed split: a preview of the layout, never to be published.")
    ] = False,
) -> None:
    """Build the public release: own photos without EXIF, online menus as annotations plus a source link."""
    from menubench.data.export import ExportError, export_release
    from menubench.data.real import RealStore

    try:
        report = export_release(RealStore(root), out, card, draft=draft)
    except ExportError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None
    for part, n in report.rows.items():
        typer.echo(f"  {part}: {n} pages")
    for menu_id, reason in report.skipped:
        typer.echo(f"  skipped {menu_id}: {reason}", err=True)
    typer.echo(f"Wrote {out}. Check every photo for faces and plates before uploading.")
    if draft:
        typer.echo("DRAFT: the split is not fixed, do not publish this.", err=True)
