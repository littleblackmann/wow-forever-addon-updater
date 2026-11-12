"""Exercise real official releases against an isolated empty client, never the live game."""
from pathlib import Path
import json
import tempfile
import sys
import shutil
from unittest.mock import patch

import updater as u


def main():
    live_folders = tuple(n for p in u.PACKAGES for n in p.managed_folders if (u.ADDONS / n).is_dir())
    live_before = u.read_live(u.ADDONS, live_folders)
    reports = []
    with tempfile.TemporaryDirectory(prefix='空白客戶端-') as tmp:
        root = Path(tmp)
        game = root / '朋友的遊戲'
        (game / '_forever_').mkdir(parents=True)
        (game / '_forever_/Wow.exe').write_bytes(b'isolated test, not an executable')
        (game / '.build.info').write_bytes((u.GAME / '.build.info').read_bytes())
        addons = game / '_forever_/Interface/AddOns'
        assert game.resolve() != u.GAME.resolve()
        def report(*row):
            reports.append(row)
            print(' | '.join(row), flush=True)
        baseline = root / 'baselines'
        if '--existing' in sys.argv:
            addons.mkdir(parents=True)
            baseline.mkdir()
            for folder in (*live_folders, 'XiaoHeiAddonHub'):
                shutil.copytree(u.ADDONS / folder, addons / folder)
            if '--no-baselines' not in sys.argv:
                for pkg in u.PACKAGES:
                    version = u.installed_version(u.ADDONS, pkg)
                    name = f'{pkg.key}-{version}.zip'
                    shutil.copy2(u.BASELINES / name, baseline / name)
        args = dict(game=game, backups=root/'backups', baselines=baseline, running=lambda: False)
        if '--online-catalog' in sys.argv:
            import online
            catalog = online.sync_catalog()
            assert catalog.identity is not None, catalog.note
            args['catalog'] = catalog
        # With --cached, use the previously verified original ZIPs as fixture downloads.
        if '--cached' in sys.argv:
            releases, downloads = {}, {}
            for pkg in u.PACKAGES:
                version = u.installed_version(u.ADDONS, pkg)
                url = 'https://fixture.invalid/' + pkg.key
                raw = (u.BASELINES / f'{pkg.key}-{version}.zip').read_bytes()
                releases[pkg.key] = u.Release(version, url, len(raw))
                downloads[url] = raw
            with patch.object(u, 'find_release', side_effect=lambda p, _: releases[p.key]), \
                    patch.object(u, 'fetch', side_effect=lambda url, _: downloads[url]):
                result = u.run_updates(True, report, **args)
        else:
            # Retain temporary old fixtures inside this test, not in the user's Recycle Bin.
            with patch.object(u, 'recycle_completed_file'):
                result = u.run_updates(True, report, **args)
        assert result == (16, 16, 0), (result, reports)
        assert not (addons / 'RXPGuides').exists()
        assert not (addons / 'ForeverQuestPins').exists()
        assert not (addons / 'AmobiCompanion').exists()
        assert (addons / 'XiaoHeiAddonHub/Routes.lua').is_file()
        atlas = (addons / 'AtlasLootClassic_DungeonsAndRaids/data.lua').read_text(encoding='utf-8-sig')
        assert '永恆團隊' in atlas and '族長之廳' in atlas and '海加爾山' in atlas
        # Repeated check must be idempotent and see all installed official packages as current.
        if '--cached' in sys.argv:
            with patch.object(u, 'find_release', side_effect=lambda p, _: releases[p.key]):
                assert u.run_updates(False, lambda *r: None, **args) == (0, 0, 0)
        else:
            assert u.run_updates(False, lambda *r: None, **args) == (0, 0, 0)
        print('PASS: complete empty-client install, localized AtlasLoot, hub, preserved baselines and idempotent check', flush=True)
    assert live_before == u.read_live(u.ADDONS, live_folders)
    print('PASS: all live managed addons unchanged', flush=True)


if __name__ == '__main__':
    main()
