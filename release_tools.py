"""Prepare explicit allowlisted public assets; game/settings/backups are never copied."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
import argparse
import dis

import updater as u
import online


def embedded_version(executable: Path) -> str:
    from PyInstaller.archive.readers import CArchiveReader
    try:
        code = CArchiveReader(str(executable)).open_embedded_archive('PYZ.pyz').extract('online')
        previous = None
        for instruction in dis.get_instructions(code):
            if instruction.opname == 'STORE_NAME' and instruction.argval == 'APP_VERSION':
                if previous is not None and previous.opname == 'LOAD_CONST' and isinstance(previous.argval, str):
                    return previous.argval
            previous = instruction
    except Exception as exc:
        raise u.SkipUpdate('無法讀取打包程式的版本，請先重新建置exe') from exc
    raise u.SkipUpdate('打包程式沒有可辨識的版本')


def prepare(output: Path, executable: Path | None, catalog_only: bool = False):
    if not catalog_only and (executable is None or embedded_version(executable) != online.APP_VERSION):
        raise u.SkipUpdate('exe內版號與待發布版號不一致，請重新建置，避免朋友一直收到同一舊版')
    output.mkdir(parents=True, exist_ok=True)
    payload = output / 'customizations.zip'
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as z:
        for file in sorted(u.CUSTOMIZATIONS.rglob('*')):
            if file.is_file() and file.suffix in {'.zip', '.json'}:
                z.write(file, 'customizations/' + file.relative_to(u.CUSTOMIZATIONS).as_posix())
    catalog = {'schema': 1, 'revision': datetime.now().strftime('%Y.%m.%d.%H%M%S'),
               'minimum_app': online.CATALOG_MIN_APP, 'packages': [asdict(p) for p in u.PACKAGES],
               'customizations': {'name': payload.name, 'sha256': hashlib.sha256(payload.read_bytes()).hexdigest()}}
    raw = json.dumps(catalog, ensure_ascii=False, indent=2).encode('utf-8')
    online.parse_catalog(raw)
    online.unpacked_files(payload, u.PACKAGES)
    (output / 'catalog.json').write_bytes(raw)
    catalog_assets = [output / 'catalog.json', payload]
    assets = list(catalog_assets)
    if not catalog_only:
        shutil.copy2(executable, output / 'XiaoHeiForeverUpdater.exe')
        share = output / f'XiaoHeiForeverUpdater-v{online.APP_VERSION}.zip'
        with zipfile.ZipFile(share, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(executable, '永恆插件更新器/永恆插件更新器.exe')
            z.write(u.APP / '使用說明.txt', '永恆插件更新器/使用說明.txt')
        with zipfile.ZipFile(share) as z:
            assert z.testzip() is None
        assets = [output / 'XiaoHeiForeverUpdater.exe', share]
        # Copy this public descriptor to the website after verifying the uploaded
        # release, so website visitors need not spend GitHub's shared API quota.
        (output / 'website-release.json').write_text(json.dumps({
            'repository': online.REPOSITORY, 'tag_name': 'v'+online.APP_VERSION,
            'draft': False, 'prerelease': False, 'assets': [{
                'name': share.name, 'state': 'uploaded', 'size': share.stat().st_size,
                'digest': 'sha256:'+hashlib.sha256(share.read_bytes()).hexdigest(),
                'browser_download_url': f'https://github.com/{online.REPOSITORY}/releases/download/v{online.APP_VERSION}/{share.name}',
            }],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'CATALOG-SHA256SUMS').write_text(''.join(
            hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
            for p in catalog_assets), encoding='ascii')
    (output / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
        for p in assets), encoding='ascii')
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--exe', type=Path, default=u.APP / '永恆插件更新器.exe')
    parser.add_argument('--catalog-only', action='store_true', help='只準備整合資料，不發布介面程式')
    args = parser.parse_args()
    prepare(args.output, args.exe, args.catalog_only)
