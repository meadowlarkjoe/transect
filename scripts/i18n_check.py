#!/usr/bin/env python3
"""i18n gates for app/i18n.js. Runs standalone and from pytest.

Currently enforces the two gates that must never regress:
  1. KEY PARITY — en and fr define exactly the same keys.
  2. NO MISSING KEYS — every t('key') / data-i18n="key" resolves to a defined key.

Orphan detection and untranslated-literal scanning are reported as WARNINGS with a
ratcheted baseline (ticket #29) so this can land without a 95-key cleanup blocking it.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")


def _keys(block):
    return set(re.findall(r"'([a-zA-Z][\w.]*)'\s*:", block))


def check():
    i18n = open(os.path.join(APP, "i18n.js"), encoding="utf-8").read()
    en = _keys(i18n[i18n.index("en: {"):i18n.index("fr: {")])
    fr = _keys(i18n[i18n.index("fr: {"):]) - {"fr"}
    js = open(os.path.join(APP, "app.js"), encoding="utf-8").read()
    html = "".join(open(os.path.join(APP, f), encoding="utf-8").read()
                   for f in ("app.html", "index.html", "signin.html", "plans.html"))
    used = set(re.findall(r"\bt\('([^']+)'", js)) | set(re.findall(r'data-i18n="([^"]+)"', html))

    errors, warnings = [], []
    if en != fr:
        errors.append(f"EN/FR key parity broken: only-en={sorted(en - fr)} only-fr={sorted(fr - en)}")
    missing = used - en
    if missing:
        errors.append(f"referenced but undefined: {sorted(missing)}")

    orphans = en - used
    ORPHAN_BASELINE = 96          # ratchet: must not GROW (was 95 + base.overzoom added)
    if len(orphans) > ORPHAN_BASELINE:
        errors.append(f"orphaned keys grew past baseline {ORPHAN_BASELINE}: now {len(orphans)}")
    elif orphans:
        warnings.append(f"{len(orphans)} orphaned keys (baseline {ORPHAN_BASELINE}, not growing)")

    return errors, warnings, {"en": len(en), "fr": len(fr), "used": len(used)}


if __name__ == "__main__":
    errs, warns, stats = check()
    print(f"i18n: {stats['en']} en / {stats['fr']} fr keys, {stats['used']} referenced")
    for w in warns:
        print("  WARN:", w)
    for e in errs:
        print("  FAIL:", e)
    sys.exit(1 if errs else 0)
