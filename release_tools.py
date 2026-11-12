"""Prepare explicit allowlisted public assets; game/settings/backups are never copied."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
import argparse

import updater as u
import online


def prepare(output: Path, executable: Path):
    output.mkdir(parents=True, exist_ok=True)
    payload = output / 'customizations.zip'
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as z:
        for file in sorted(u.CUSTOMIZATIONS.rglob('*')):
            if file.is_file() and file.suffix in {'.zip', '.json'}:
                z.write(file, 'customizations/' + file.relative_to(u.CUSTOMIZATIONS).as_posix())
    catalog = {'schema': 1, 'revision': datetime.now().strftime('%Y.%m.%d.%H%M%S'),
               'minimum_app': online.APP_VERSION, 'packages': [asdict(p) for p in u.PACKAGES],
               'customizations': {'name': payload.name, 'sha256': hashlib.sha256(payload.read_bytes()).hexdigest()}}
    raw = json.dumps(catalog, ensure_ascii=False, indent=2).encode('utf-8')
    online.parse_catalog(raw)
    online.unpacked_files(payload, u.PACKAGES)
    (output / 'catalog.json').write_bytes(raw)
    shutil.copy2(executable, output / 'XiaoHeiForeverUpdater.exe')
    share = output / f'XiaoHeiForeverUpdater-v{online.APP_VERSION}.zip'
    with zipfile.ZipFile(share, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(executable, '永恆插件更新器/永恆插件更新器.exe')
        z.write(u.APP / '使用說明.txt', '永恆插件更新器/使用說明.txt')
    with zipfile.ZipFile(share) as z:
        assert z.testzip() is None
    (output / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
        for p in (output / 'catalog.json', payload, output / 'XiaoHeiForeverUpdater.exe', share)), encoding='ascii')
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--exe', type=Path, default=u.APP / '永恆插件更新器.exe')
    args = parser.parse_args()
    prepare(args.output, args.exe)
