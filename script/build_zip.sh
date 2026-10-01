#!/usr/bin/env bash
# Impacchetta il plugin come dist/bark-<versione>.zip (Tools -> Plugins -> Add).
# La versione si legge da bark/manifest.json: aumentala prima di fare una release.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 - <<'PY'
import json, pathlib, zipfile

root = pathlib.Path('.')
version = json.loads((root / 'bark' / 'manifest.json').read_text())['version']
out = root / 'dist' / f'bark-{version}.zip'
out.parent.mkdir(exist_ok=True)
if out.exists():
    out.unlink()

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in sorted((root / 'bark').rglob('*')):
        if path.is_dir() or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        z.write(path, path.as_posix())   # dentro lo zip: bark/manifest.json, bark/qt.py...
print(f'built {out}')
PY
