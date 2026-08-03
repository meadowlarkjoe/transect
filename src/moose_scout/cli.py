"""Command-line interface: `moose-scout <stage> --aoi <name>`."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import legal as legal_stage
from . import pipeline
from .config import Context

app = typer.Typer(add_completion=False, help="DIY hunt-area intelligence pipeline.")
console = Console()


def _ctx(aoi: str, radius_km: float | None = None) -> Context:
    ctx = Context.for_aoi(aoi)
    if radius_km:
        ctx.aoi.bbox_halfwidth_km = float(radius_km)
    return ctx


@app.command()
def legal(aoi: str = typer.Option(..., help="AOI config name, e.g. fire_lake")):
    """Stage 0 — resolve zone/season/tenure and print the huntability gate."""
    ctx = _ctx(aoi)
    a = legal_stage.assess(ctx)

    if a.unverified:
        verdict = "[yellow]UNVERIFIED — acquire tenure data first[/]"
    elif a.diy_possible:
        verdict = "[green]DIY possible[/]"
    else:
        verdict = "[red]No DIY access found[/]"
    console.print(
        Panel.fit(
            f"[bold]{ctx.aoi.title}[/]\n"
            f"Zone: [bold]{a.zone or '?'}[/]   "
            f"{'NORTH' if a.north_of_52 else 'SOUTH'} of 52°N   "
            f"Residency: {a.residency}\n{verdict}",
            title="Legal / tenure gate",
        )
    )
    console.print(f"[bold]Season:[/] {a.season_summary}")

    if a.huntable_tenures:
        console.print("[green]Huntable tenures:[/] " + ", ".join(t.value for t in a.huntable_tenures))
    if a.blocked_tenures:
        console.print("[red]Blocked tenures:[/] " + ", ".join(t.value for t in a.blocked_tenures))

    if a.flags:
        t = Table(title="Flags", show_header=False, box=None)
        for f in a.flags:
            t.add_row("•", f)
        console.print(t)
    if a.verify:
        t = Table(title="[yellow]Verify before you travel[/]", show_header=False, box=None)
        for v in a.verify:
            t.add_row("!", v)
        console.print(t)


def _run_stage(aoi: str, name: str) -> None:
    ctx = _ctx(aoi)
    console.print(f"[cyan]▶ {name}[/] ({ctx.aoi.title})")
    try:
        pipeline.run_stage(name, ctx)
        console.print(f"[green]✓ {name} done[/]")
    except NotImplementedError as e:
        console.print(f"[yellow]… {name} not implemented yet:[/] {e}")


@app.command()
def acquire(aoi: str = typer.Option(...)):
    """Stage 1 — fetch DEM, écoforestière, hydro, roads, Sentinel-2, tenure."""
    from .acquire import run as acquire_run

    ctx = _ctx(aoi)
    console.print(f"[cyan]▶ acquire[/] ({ctx.aoi.title})")
    status = acquire_run(ctx)
    t = Table(title="Acquisition", show_header=True, box=None)
    t.add_column("source")
    t.add_column("status")
    styles = {"ok": "green", "todo": "yellow"}
    for name, st in status.items():
        style = styles.get(st, "red")
        t.add_row(name, f"[{style}]{st}[/]")
    console.print(t)


@app.command()
def terrain(aoi: str = typer.Option(...)):
    """Stage 2 — slope/aspect/TPI/TWI/funnels/viewshed + road verification."""
    _run_stage(aoi, "terrain")


@app.command()
def habitat(aoi: str = typer.Option(...)):
    """Stage 3 — moose HSM (+ thermal-refuge and rut-site layers)."""
    _run_stage(aoi, "habitat")


@app.command()
def access(aoi: str = typer.Option(...)):
    """Stage 4 — multi-modal extraction cost + pressure + huntability + camps."""
    _run_stage(aoi, "access")


@app.command()
def synth(aoi: str = typer.Option(...)):
    """Stage 5/6 — focus areas + Claude-synthesized annotated brief."""
    _run_stage(aoi, "synth")


@app.command()
def export(aoi: str = typer.Option(...)):
    """Stage 7 — GPX/KML (OnX) + GeoPDF + offline tiles + web map."""
    _run_stage(aoi, "export")


@app.command()
def transect(aoi: str = typer.Option(...)):
    """Assemble the Transect data contract (transect.json): camps + wind + weather."""
    ctx = _ctx(aoi)
    from . import contract
    d = contract.build(ctx)
    console.print(f"[green]✓ transect.json[/] · {len(d['camps'])} camps · "
                  f"{len(d['areas'])} areas · {len(d['waypoints'])} waypoints · "
                  f"weather: {d['weather']['source']}")


@app.command()
def run(
    aoi: str = typer.Option(...),
    radius: float = typer.Option(None, help="Search radius in km from the AOI centre "
                                            "(e.g. 5/10/20/50/100). Re-acquires at the new extent."),
):
    """Full pipeline: legal gate, then acquire → export. Optional --radius sets the
    Phase-1 search extent (clears the AOI cache so data is re-fetched to match)."""
    import shutil

    from .config import cache_dir

    ctx = _ctx(aoi, radius)
    if radius:
        shutil.rmtree(cache_dir(aoi), ignore_errors=True)  # extent changed -> refetch
        console.print(f"[cyan]Search radius set to {radius} km[/] (cache cleared for re-acquire)")
    # legal gate (respects overridden radius via ctx)
    a = legal_stage.assess(ctx)
    console.print(f"[bold]Zone {a.zone}[/] · {'DIY possible' if a.diy_possible else 'restricted'} · "
                  f"radius {ctx.aoi.bbox_halfwidth_km} km")
    console.rule("[bold]Pipeline[/]")
    for name in ("acquire", "terrain", "habitat", "access", "synth", "export", "contract"):
        console.print(f"[cyan]▶ {name}[/]")
        try:
            pipeline.run_stage(name, ctx)
            console.print(f"[green]✓ {name}[/]")
        except NotImplementedError as e:
            console.print(f"[yellow]… {name}: {e}[/]")


if __name__ == "__main__":
    app()
