#!/usr/bin/env python3
"""i18n gates for app/i18n.js. Runs standalone, from pytest, and from deploy.sh.

The app was built English-first and internationalised in a later retrofit, so the
dictionary is fully built out (EN/FR parity) but the render code is only partly wired
to it. These gates freeze that debt where it is and make it impossible to GROW — the
patchiness can only shrink from here.

HARD gates (any failure blocks the deploy / fails the test):
  1. KEY PARITY        — en and fr define exactly the same keys.
  2. NO MISSING KEYS   — every t('key') / data-i18n[-ph]="key" resolves to a defined key.
  3. t() KEY SHAPE     — t()'s first argument is always a dotted lower-case key, never a
                         bare English sentence. Stops the "t('Analysis failed: '+e)"
                         anti-pattern that silently prints English in both languages.

RATCHET gates (a frozen baseline that must not increase):
  4. ORPHAN KEYS       — keys defined but never referenced (unfinished wiring). Wiring a
                         key to the UI removes it from this set; the baseline drops with it.
  5. HTML UNTRANSLATED — visible text nodes and title/placeholder attributes in the four
                         HTML shells that carry no data-i18n. Marketing/public copy debt.

Generated data files (area_detail.js = window.AREA_DETAIL, data.js) are NOT app copy and
are deliberately out of scope: their strings belong to the legend/contract epic, not here.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")

HTML_FILES = ("app.html", "index.html", "signin.html", "plans.html")
JS_FILES = ("app.js",)              # the only file that renders UI via t()

# Ratchet baselines: the CURRENT debt, frozen. LOWER these as debt is paid down
# (#28 wiring); never raise them. The gate's job is to stop the patchiness GROWING.
ORPHAN_BASELINE = 84                # dictionary keys defined but not yet wired to the UI
HTML_TEXT_BASELINE = 85             # untranslated HTML text nodes (mostly public pages)
HTML_ATTR_BASELINE = 3              # untranslated title/placeholder attributes

# How far the real number may sit below its baseline before the gate insists you write
# the new one down. Small, so slack cannot quietly accumulate into room for new debt;
# non-zero, so a one-key wobble does not fail the build.
SLACK = 2

# Not user copy: brand, language chips, the domain, export-format acronyms.
HTML_SKIP = {"TRANSECT", "EN", "FR", "transect.joejmeadows.com",
             "GPX — OnX / Garmin", "KML — Google Earth"}

KEY_RE = re.compile(r"^[a-z][\w]*(\.[\w]+)*$")


def _dict_keys(block):
    return set(re.findall(r"'([a-zA-Z][\w.]*)'\s*:", block))


def _referenced_keys(js, html):
    used = set()
    # BOTH helpers. tf() interpolates {placeholders}; missing it here meant every key
    # only ever used through tf() looked ORPHANED, which is the gate quietly lying
    # about debt it cannot see.
    for m in re.finditer(r"\b(?:t|tf)\(\s*'([^']*)'", js):
        used.add(m.group(1))
    used |= set(re.findall(r'data-i18n="([^"]+)"', html))
    used |= set(re.findall(r'data-i18n-ph="([^"]+)"', html))
    return used


def _bad_shape_keys(js):
    """t()/tf() first args that are not dotted-lower keys — raw English shoved through."""
    bad = []
    for m in re.finditer(r"\b(?:t|tf)\(\s*'((?:[^'\\]|\\.)*)'", js):
        k = m.group(1)
        if not KEY_RE.match(k):
            bad.append(k)
    return bad


def _html_debt():
    """Count untranslated text nodes and title/placeholder attrs across the HTML shells."""
    text, attr = [], []
    for f in HTML_FILES:
        s = open(os.path.join(APP, f), encoding="utf-8").read()
        s = re.sub(r"<script[\s\S]*?</script>", "", s)
        s = re.sub(r"<style[\s\S]*?</style>", "", s)
        for m in re.finditer(r">([^<>{}]+)<", s):
            txt = m.group(1).strip()
            if len(re.sub(r"[^A-Za-z]", "", txt)) < 2 or txt in HTML_SKIP:
                continue
            opening = s[max(0, m.start() - 200):m.start() + 1].split("<")[-1]
            if "data-i18n" not in opening:
                text.append((f, txt[:60]))
        for m in re.finditer(r'\b(title|placeholder)="([^"]*[A-Za-z]{2,}[^"]*)"', s):
            if m.group(2) not in HTML_SKIP:
                attr.append((f, m.group(1), m.group(2)[:50]))
    return text, attr


def check():
    i18n = open(os.path.join(APP, "i18n.js"), encoding="utf-8").read()
    en = _dict_keys(i18n[i18n.index("en: {"):i18n.index("fr: {")])
    fr = _dict_keys(i18n[i18n.index("fr: {"):]) - {"fr"}
    js = "".join(open(os.path.join(APP, f), encoding="utf-8").read() for f in JS_FILES)
    html = "".join(open(os.path.join(APP, f), encoding="utf-8").read() for f in HTML_FILES)

    used = _referenced_keys(js, html)
    errors, warnings = [], []

    # 1. parity
    if en != fr:
        errors.append(f"EN/FR key parity broken: only-en={sorted(en - fr)} only-fr={sorted(fr - en)}")

    # 2. missing
    missing = used - en
    if missing:
        errors.append(f"referenced but undefined: {sorted(missing)}")

    # 3. t() shape
    bad = _bad_shape_keys(js)
    if bad:
        errors.append(f"t() called with non-key argument (English through t()): {bad}")

    # 4. orphan ratchet
    orphans = en - used
    if len(orphans) > ORPHAN_BASELINE:
        errors.append(f"orphaned keys grew past baseline {ORPHAN_BASELINE}: now {len(orphans)} "
                      f"(newly orphaned: {sorted(orphans)})")
    elif orphans:
        warnings.append(f"{len(orphans)} orphaned keys (baseline {ORPHAN_BASELINE}, not growing)")

    # 5. HTML debt ratchet
    text, attr = _html_debt()
    if len(text) > HTML_TEXT_BASELINE:
        errors.append(f"untranslated HTML text grew past baseline {HTML_TEXT_BASELINE}: now {len(text)} "
                      f"(e.g. {[t[1] for t in text[-3:]]})")
    elif text:
        warnings.append(f"{len(text)} untranslated HTML text nodes (baseline {HTML_TEXT_BASELINE}, not growing)")
    if len(attr) > HTML_ATTR_BASELINE:
        errors.append(f"untranslated HTML attrs grew past baseline {HTML_ATTR_BASELINE}: now {len(attr)}")
    elif attr:
        warnings.append(f"{len(attr)} untranslated HTML attrs (baseline {HTML_ATTR_BASELINE}, not growing)")

    # 6. THE RATCHET MUST ACTUALLY RATCHET.
    #
    # A baseline that only ever blocks growth still leaves SLACK: pay down 11 keys and
    # the gate will silently absorb the next 11 new untranslated strings without a
    # word. That is how the debt stopped shrinking last time. So once the real number
    # drops meaningfully below its baseline, the check FAILS and tells you to write the
    # new number down — the baseline can only travel one way.
    for label, actual, baseline, const in (
            ("orphaned keys", len(orphans), ORPHAN_BASELINE, "ORPHAN_BASELINE"),
            ("untranslated HTML text", len(text), HTML_TEXT_BASELINE, "HTML_TEXT_BASELINE"),
            ("untranslated HTML attrs", len(attr), HTML_ATTR_BASELINE, "HTML_ATTR_BASELINE")):
        if actual < baseline - SLACK:
            errors.append(
                f"{label} is down to {actual} but {const} still says {baseline} — "
                f"lower it to {actual} in scripts/i18n_check.py so the gap cannot be "
                f"refilled silently.")

    stats = {"en": len(en), "fr": len(fr), "used": len(used),
             "orphans": len(orphans), "html_text": len(text), "html_attr": len(attr)}
    return errors, warnings, stats


if __name__ == "__main__":
    errs, warns, stats = check()
    print(f"i18n: {stats['en']} en / {stats['fr']} fr keys, {stats['used']} referenced, "
          f"{stats['orphans']} orphan, {stats['html_text']} html-text / {stats['html_attr']} html-attr debt")
    for w in warns:
        print("  WARN:", w)
    for e in errs:
        print("  FAIL:", e)
    sys.exit(1 if errs else 0)
