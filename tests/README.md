# Tests

Run from the repo root:

    .venv/bin/python -m pytest tests/ -q      # or: python3 -m pytest, if the geo stack is installed

`conftest.py` puts `src/` on the path, so the suite runs from a bare clone — the whole
point of it existing is to gate a change before anything is set up.

## What each file gates
- `test_legal.py` — the legal/tenure filter (the load-bearing gate).
- `test_contract_shape.py` — the fields the front end binds to, against a committed
  contract fixture (`fixtures/rouyn.transect.json`, a complete fresh run). Regenerate:
  `ssh <droplet> 'docker exec transect-api cat /app/outputs/rouyn/transect.json' > tests/fixtures/rouyn.transect.json`
- `test_frontend_static.py` — parses `app.js` and runs `scripts/check_layer_paint.js`
  (catches setPaintProperty on the wrong layer type — the bug that killed the tab bar).
- `test_i18n.py` — EN/FR key parity + no missing keys (`scripts/i18n_check.py`).
