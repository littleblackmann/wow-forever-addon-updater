from pathlib import Path
from io import BytesIO
import tempfile
import unittest
import zipfile
import hashlib
import json
import os
from unittest.mock import patch

import updater as u
import online as o
import test_updater as fixtures


class HistoricalTranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pkg = u.Package('sample', 'Sample', 'Sample', 'official/sample', '')
        self.toc = ('Sample/Sample.toc', b'## Version: 1.0\n')
        self.original = {'sample/sample.toc': self.toc, 'sample/data.lua': ('Sample/data.lua', b'name="English"\n')}
        self.local = dict(self.original, **{'sample/data.lua': ('Sample/data.lua', b'name="Chinese"\n')})
        self.custom = self.root/'custom'; self.custom.mkdir()
        def zipped(data):
            stream = BytesIO()
            with zipfile.ZipFile(stream, 'w') as z: z.writestr('Sample/data.lua', data)
            return stream.getvalue()
        with zipfile.ZipFile(self.custom/'history.zip', 'w') as z:
            z.writestr('sample-1.0/base.zip', zipped(b'name="English"\n'))
            z.writestr('sample-1.0/local.zip', zipped(b'name="Chinese"\n'))
        # Today's patch deliberately overlaps the old author's database.
        (self.custom/'sample').mkdir()
        for label, data in [('base', b'name="New author"\n'), ('local', b'name="New Chinese"\n')]:
            (self.custom/f'sample/{label}.zip').write_bytes(zipped(data))

    def previous(self, live):
        return u.previous_package(self.pkg, self.original, live, self.root, ('Sample',), self.custom, self.custom)

    def test_fresh_manager_recognizes_exact_old_translation_and_preserves_other_edits(self):
        live = dict(self.local, **{'sample/own.lua': ('Sample/own.lua', b'personal=true')})
        previous = self.previous(live)
        self.assertEqual(previous, self.local)
        desired = dict(self.original, **{'sample/data.lua': ('Sample/data.lua', b'name="Updated Chinese"\n')})
        merged, _ = u.merge_files(previous, live, desired, self.root)
        self.assertEqual(merged['sample/own.lua'], live['sample/own.lua'])
        self.assertEqual(merged['sample/data.lua'], desired['sample/data.lua'])

    def test_unrecognized_personal_change_is_not_treated_as_known_translation(self):
        live = dict(self.local, **{'sample/data.lua': ('Sample/data.lua', b'name="Personal"\n')})
        with self.assertRaises(u.SkipUpdate): self.previous(live)

    def test_exact_author_files_do_not_need_backwards_translation(self):
        self.assertEqual(self.previous(self.original), self.original)

    def test_fresh_manager_upgrades_known_old_hub_and_keeps_unrelated_file(self):
        addons = self.root/'Interface/AddOns'
        folder = addons/'XiaoHeiAddonHub'; folder.mkdir(parents=True)
        old_toc = b'## Interface: 16001\n## Version: 0.1.11\nHub.lua\n'
        new_toc = b'## Interface: 16001\n## Version: 0.1.14\nHub.lua\n'
        old = BytesIO()
        with zipfile.ZipFile(old, 'w') as z:
            z.writestr('XiaoHeiAddonHub/XiaoHeiAddonHub.toc', old_toc)
            z.writestr('XiaoHeiAddonHub/Hub.lua', b'old=true\n')
        (folder/'XiaoHeiAddonHub.toc').write_bytes(old_toc)
        (folder/'Hub.lua').write_bytes(b'old=true\n')
        (folder/'personal.lua').write_bytes(b'keep=true\n')
        with zipfile.ZipFile(self.custom/'hub.zip', 'w') as z:
            z.writestr('XiaoHeiAddonHub/XiaoHeiAddonHub.toc', new_toc)
            z.writestr('XiaoHeiAddonHub/Hub.lua', b'new=true\n')
        with zipfile.ZipFile(self.custom/'history.zip', 'a') as z:
            z.writestr('hub-0.1.11/hub.zip', old.getvalue())
        with patch.object(u, 'CUSTOMIZATIONS', self.custom):
            u.install_hub(addons, '16001', lambda: False, self.custom, backups=self.root/'backups')
        self.assertEqual((folder/'XiaoHeiAddonHub.toc').read_bytes(), new_toc)
        self.assertEqual((folder/'Hub.lua').read_bytes(), b'new=true\n')
        self.assertEqual((folder/'personal.lua').read_bytes(), b'keep=true\n')


class CurrentCatalogAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.InstallTests(); self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.pkg = self.f.pkg
        self.author = b'local label = "New author"\nlocal value = 2\n'
        self.translated = self.author.replace(b'New author', b'Current Chinese')
        self.raw, self.release = self.f.archive('2.0', {'Sample/main.lua': self.author})
        self.archive = self.f.root/'official.zip'; self.archive.write_bytes(self.raw)
        self.original = u.read_zip(self.archive, self.pkg.managed_folders)
        for relative, contents in self.original.values():
            file = self.f.addons/relative; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(contents)
        self.main = self.f.addons/'Sample/main.lua'; self.main.write_bytes(self.translated)
        self.personal = self.f.addons/'Sample/personal.lua'; self.personal.write_bytes(b'keep = true\n')
        os.utime(self.main, (1600000000, 1600000000)); self.before_stat = self.main.stat()
        self.old_custom = self.f.root/'old-custom'
        for root, base, local in [(self.f.custom, self.author, self.translated),
                                  (self.old_custom, b'local label = "English"\nlocal value = 1\n', b'local label = "Old Chinese"\nlocal value = 1\n')]:
            (root/'sample').mkdir(parents=True)
            for label, contents in [('base', base), ('local', local)]:
                with zipfile.ZipFile(root/f'sample/{label}.zip', 'w') as z: z.writestr('Sample/main.lua', contents)
        self.f.baselines.mkdir()
        old, _ = self.f.archive('1.0'); (self.f.baselines/'sample-1.0.zip').write_bytes(old)
        self.identity = 'a'*64; self.old_identity = 'b'*64
        self.catalog = o.Catalog((self.pkg,), self.f.custom, self.identity, 'current')
        self.state = self.f.baselines/'.catalog-state.json'
        self.state.write_text(json.dumps({'sample': self.old_identity, 'hub': self.identity}), encoding='utf-8')
        (self.f.addons/'XiaoHeiAddonHub').mkdir()

    def run_update(self):
        rows = []
        with patch.object(u, 'find_release', return_value=self.release), patch.object(u, 'fetch', return_value=self.raw), patch.object(u, 'recycle_completed_file'):
            result = u.run_updates(True, lambda *r: rows.append(r), game=self.f.game, baselines=self.f.baselines,
                                   backups=self.f.backups, running=lambda: False, catalog=self.catalog)
        return result, rows

    def test_other_manager_already_updated_game_adopts_state_without_rewriting_files(self):
        with patch.object(o, 'previous_customizations', side_effect=u.SkipUpdate('old cache missing')) as old:
            result, rows = self.run_update()
            self.assertEqual(result, (1, 1, 0)); old.assert_not_called()
            self.assertIn('更新紀錄已同步', rows[0][-1])
            self.assertEqual(self.run_update()[0], (0, 0, 0))
        self.assertEqual(self.main.read_bytes(), self.translated)
        self.assertEqual(self.personal.read_bytes(), b'keep = true\n')
        self.assertEqual(self.main.stat().st_mtime_ns, self.before_stat.st_mtime_ns)
        self.assertEqual(self.main.stat().st_ino, self.before_stat.st_ino)
        self.assertEqual(json.loads(self.state.read_text())['sample'], self.identity)
        self.assertEqual((self.f.baselines/'sample-2.0.zip').read_bytes(), self.raw)
        self.assertTrue((self.f.baselines/'sample-1.0.zip').exists())

    def test_unrecognized_change_remains_visible_and_old_state_is_not_replaced(self):
        self.main.write_bytes(b'local label = "Personal edit"\nlocal value = 99\n')
        before = u.read_live(self.f.addons, self.pkg.managed_folders)
        with patch.object(o, 'previous_customizations', return_value=self.old_custom) as old:
            result, rows = self.run_update(); old.assert_called_once()
        self.assertEqual(result[2], 1); self.assertIn('保留現況', rows[0][-1])
        self.assertEqual(u.read_live(self.f.addons, self.pkg.managed_folders), before)
        self.assertEqual(json.loads(self.state.read_text())['sample'], self.old_identity)

    def test_recognition_keeps_unrelated_personal_edits_during_later_author_update(self):
        live = u.read_live(self.f.addons, self.pkg.managed_folders)
        previous = u.previous_package(self.pkg, self.original, live, self.f.root, self.pkg.managed_folders,
                                      self.f.custom, self.old_custom)
        desired = dict(previous); desired['sample/new.lua'] = ('Sample/new.lua', b'new_author_feature = true\n')
        merged, _ = u.merge_files(previous, live, desired, self.f.root)
        self.assertEqual(merged['sample/personal.lua'][1], b'keep = true\n')
        self.assertEqual(merged['sample/main.lua'][1], self.translated)
        self.assertIn('sample/new.lua', merged)

    def test_external_author_update_with_personal_extra_file_uses_verified_author_baseline(self):
        self.main.write_bytes(self.author)
        with patch.object(o, 'previous_customizations', side_effect=u.SkipUpdate('old cache missing')) as old:
            result, rows = self.run_update(); old.assert_not_called()
        self.assertEqual(result, (1, 1, 0))
        self.assertEqual(self.main.read_bytes(), self.translated)
        self.assertEqual(self.personal.read_bytes(), b'keep = true\n')

    def test_metadata_adoption_still_checks_game_running_before_saving_baseline(self):
        with patch.object(u, 'fetch', return_value=self.raw):
            with self.assertRaises(u.SkipUpdate):
                u.install_package(self.pkg, self.release, self.f.addons, self.pkg.managed_folders, '2.0', '16001',
                                  self.f.backups, self.f.baselines, lambda: True, self.f.custom, self.old_custom)
        self.assertFalse((self.f.baselines/'sample-2.0.zip').exists())
        self.assertEqual(json.loads(self.state.read_text())['sample'], self.old_identity)


if __name__ == '__main__': unittest.main()
