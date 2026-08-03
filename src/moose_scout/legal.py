"""Stage 0 — Legal / tenure gate.

The FIRST filter. A perfect topo pick is worthless if it's the wrong zone, the
wrong season, or inside an exclusive outfitter you can't hunt. This stage:

  1. resolves the hunting ZONE the AOI falls in,
  2. applies the RESIDENCY x 52nd-parallel access rules,
  3. classifies LAND TENURE across the AOI (crown / ZEC / réserve / pourvoirie),
  4. emits a HUNTABLE mask + a plain-language assessment with "verify" flags.

Regulations rotate (seasons, the "moose without antlers" rule, non-resident
relaxations). Nothing here is authoritative — the rule table below is a coded
snapshot to be re-confirmed live by the Claude regs resolver each run, and every
output carries an explicit "verify before you travel" flag.

Sources snapshot (2026-2028 regs, retrieved 2026-08):
  - Non-residents hunting moose SOUTH of the 52nd parallel must use an outfitter
    (>=2 services incl. lodging) OR hunt in a ZEC / wildlife reserve.
  - Non-residents hunting NORTH of the 52nd parallel must use an outfitter.
  - Quebec residents may hunt free crown land (terres du domaine de l'État),
    ZECs (daily registration/fee), and reserves (draw/reservation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .config import AOI, Context

# The 52nd parallel — the pivotal boundary near Fire Lake (52°20'N).
PARALLEL_52 = 52.0


class Tenure(str, Enum):
    CROWN = "crown"                     # terres du domaine de l'État — DIY OK
    ZEC = "zec"                         # daily registration + fee
    RESERVE = "reserve_faunique"        # SEPAQ draw / reservation
    REFUGE = "refuge_faunique"          # wildlife refuge — hunting often prohibited
    POURVOIRIE_EXCLUSIVE = "pourvoirie_exclusive"   # off-limits to DIY
    POURVOIRIE_NONEXCLUSIVE = "pourvoirie_nonexclusive"
    OTHER = "other"                     # non-hunting TFS class (fishing) — verify
    UNKNOWN = "unknown"


# Which tenures each residency class may DIY-hunt moose on. Values:
#   "yes"        — allowed
#   "outfitter"  — allowed only via outfitter services
#   "draw"       — allowed but gated by draw/reservation
#   "no"         — not permitted
#   "yes" | "outfitter" | "draw" | "verify" | "no"
ACCESS_RULES: dict[str, dict[Tenure, str]] = {
    "quebec_resident": {
        Tenure.CROWN: "yes",
        Tenure.ZEC: "yes",
        Tenure.RESERVE: "draw",
        Tenure.REFUGE: "verify",        # refuge faunique often prohibits hunting
        Tenure.POURVOIRIE_EXCLUSIVE: "no",
        Tenure.POURVOIRIE_NONEXCLUSIVE: "yes",
        Tenure.OTHER: "verify",
    },
    "non_resident_canada": {
        Tenure.CROWN: "outfitter",      # see parallel note below
        Tenure.ZEC: "yes",
        Tenure.RESERVE: "draw",
        Tenure.REFUGE: "verify",
        Tenure.POURVOIRIE_EXCLUSIVE: "outfitter",
        Tenure.POURVOIRIE_NONEXCLUSIVE: "outfitter",
        Tenure.OTHER: "verify",
    },
    "non_resident_foreign": {
        Tenure.CROWN: "outfitter",
        Tenure.ZEC: "yes",
        Tenure.RESERVE: "draw",
        Tenure.REFUGE: "verify",
        Tenure.POURVOIRIE_EXCLUSIVE: "outfitter",
        Tenure.POURVOIRIE_NONEXCLUSIVE: "outfitter",
        Tenure.OTHER: "verify",
    },
}


@dataclass
class TenurePatch:
    """A polygon of homogeneous tenure within the AOI (from the WFS layer)."""

    tenure: Tenure
    name: str
    geometry: object | None = None      # shapely geometry when data is present


@dataclass
class LegalAssessment:
    aoi: str
    zone: str | None
    north_of_52: bool
    residency: str
    acquired: bool = False              # tenure data pulled? (vs still UNVERIFIED)
    huntable_tenures: list[Tenure] = field(default_factory=list)
    blocked_tenures: list[Tenure] = field(default_factory=list)
    patches: list[TenurePatch] = field(default_factory=list)
    season_summary: str = ""
    flags: list[str] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)

    @property
    def unverified(self) -> bool:
        """True when tenure data hasn't been acquired — we can't yet say whether
        DIY is possible. Distinct from a confirmed 'no access'."""
        return not self.acquired

    @property
    def diy_possible(self) -> bool:
        return bool(self.huntable_tenures)


def _access_for(residency: str, tenure: Tenure, north_of_52: bool) -> str:
    rule = ACCESS_RULES[residency].get(tenure, "no")
    # Non-residents: north of the 52nd parallel, crown land also requires an
    # outfitter (already encoded as "outfitter" above, but make the parallel
    # dependency explicit for residents-vs-non-residents clarity).
    if residency == "quebec_resident" and tenure == Tenure.CROWN:
        return "yes"
    return rule


def classify_tenure(ctx: Context) -> list[TenurePatch] | None:
    """Load cached tenure polygons intersecting the AOI.

    Returns ``None`` when tenure data hasn't been acquired yet (the gate reports
    UNVERIFIED), or the list of patches when it has — which may be EMPTY, meaning
    the AOI is entirely crown land (terres du domaine de l'État).
    """
    from .acquire import tenure as tenure_acq  # lazy: avoids geo imports for tests

    try:
        return tenure_acq.load_tenure_patches(ctx)
    except FileNotFoundError:
        return None  # not acquired -> UNVERIFIED


def resolve_zone(ctx: Context) -> str | None:
    """Determine the hunting zone the AOI centre falls in (zones-chasse WFS)."""
    from .acquire import zones as zones_acq

    try:
        return zones_acq.zone_for_point(ctx, ctx.aoi.center.lat, ctx.aoi.center.lon)
    except Exception:
        return None


def assess(ctx: Context) -> LegalAssessment:
    aoi: AOI = ctx.aoi
    residency = aoi.hunter.residency
    north = aoi.center.lat >= PARALLEL_52

    zone = resolve_zone(ctx)
    patches = classify_tenure(ctx)

    la = LegalAssessment(
        aoi=aoi.name,
        zone=zone,
        north_of_52=north,
        residency=residency,
        acquired=patches is not None,
        patches=patches or [],
    )

    if patches is None:
        la.verify.append(
            "Tenure polygons not yet acquired — run `acquire` then re-run "
            "`legal`. Treat the whole AOI as UNVERIFIED until then."
        )
        present: set[Tenure] = set()
    else:
        # Crown land underlies any structured-territory polygons; unless the AOI
        # is fully covered by them, crown is present and (for residents) huntable.
        present = {p.tenure for p in patches}
        present.add(Tenure.CROWN)
        if patches:
            names = ", ".join(sorted({f"{p.tenure.value}:{p.name}" for p in patches})[:8])
            la.flags.append(f"Structured territories in AOI: {names}")

    # Which tenure classes are huntable for this hunter?
    for tenure in sorted(present, key=lambda t: t.value):
        access = _access_for(residency, tenure, north)
        if access == "yes":
            la.huntable_tenures.append(tenure)
        elif access == "draw":
            la.huntable_tenures.append(tenure)
            la.flags.append(f"{tenure.value}: requires draw/reservation.")
        elif access == "outfitter":
            la.blocked_tenures.append(tenure)
            la.flags.append(
                f"{tenure.value}: {residency} must use an outfitter here — not DIY."
            )
        elif access == "verify":
            la.verify.append(
                f"{tenure.value}: hunting status varies — confirm on the ground / "
                f"in the regulation before counting this area in or out."
            )
        else:
            la.blocked_tenures.append(tenure)
            la.flags.append(f"{tenure.value}: not open to {residency} (DIY).")

    la.patches = patches

    # Season / MWA summary — resolved live by the Claude regs resolver; seeded here.
    la.season_summary = (
        f"Zone {zone or '?'} · target {', '.join(aoi.season.target_dates) or 'TBD'} "
        f"· weapon {aoi.season.weapon}. Confirm season dates and the 'moose without "
        f"antlers' (MWA) rule for {aoi.season.year} against the current regulation."
    )

    # Zone provenance + recent harvest (wildlife-stats signal).
    if zone and aoi.zone_hint and zone == aoi.zone_hint:
        la.verify.append(
            f"Zone {zone} confirmed via the official MFFP zone map, but no boundary "
            f"polygon is wired for automated point-lookup — and zone {zone} is split "
            f"into sub-zones (e.g. 19 sud / 19 nord) with their own season/MWA rules. "
            f"Confirm the sub-zone for this AOI on the quebec.ca zone map."
        )
    try:
        from .acquire import zones as zones_acq

        stats = zones_acq.zone_stats(zone, aoi.species) if zone else None
        if stats:
            yrs = ", ".join(f"{y}:{n}" for y, n in stats["harvest_by_year"].items())
            la.flags.append(
                f"Zone {zone} {aoi.species} harvest (total/yr): {yrs} · latest "
                f"{stats['latest_year']} = {stats['latest_total']} "
                f"({stats['latest_male_adult']}♂ad / {stats['latest_female_adult']}♀ad)."
            )
            # Cross-reference against effort — moose-specific 'état de situation' docs.
            effort = zones_acq.effort_context(zone) if aoi.species == "moose" else None
            if effort:
                bits = []
                if "success_global_pct" in effort:
                    bits.append(f"success {effort['success_global_pct']}% all-segments")
                if "success_male_adult_pct" in effort:
                    bits.append(f"{effort['success_male_adult_pct']}% bull")
                if "hunters" in effort:
                    bits.append(f"~{effort['hunters']:,} hunters")
                if "density_per_10km2" in effort:
                    bits.append(f"density {effort['density_per_10km2']}/10km²")
                la.flags.append(f"Zone {zone} effort/success: " + " · ".join(bits) + ".")
            else:
                la.flags.append(
                    f"⚠ Zone {zone} harvest is NOT effort-normalized — no published "
                    f"'état de situation' (success rate / hunter count) for this zone, "
                    f"and zone-wide totals are dominated by more accessible areas. Treat "
                    f"as a weak proxy for {aoi.name}; the local habitat model is the real "
                    f"signal for this AOI."
                )
    except Exception:
        pass

    if north:
        la.flags.append(
            "AOI centre is NORTH of the 52nd parallel — écoforestière coverage "
            "thins here; downstream confidence is reduced (see model.confidence)."
        )
    la.verify.append(
        "Re-confirm zone, season dates, MWA rule, and tenure boundaries against "
        "quebec.ca / Données Québec before travelling. Regs rotate yearly."
    )
    return la
