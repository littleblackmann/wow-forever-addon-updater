from pathlib import Path
from io import BytesIO
import hashlib
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import updater as u


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="永恆更新測試-")
        self.root = Path(self.temp.name)
        self.game = self.root / "朋友 遊戲"
        (self.game / "_forever_").mkdir(parents=True)
        (self.game / "_forever_/Wow.exe").write_bytes(b"test only")
        (self.game / ".build.info").write_text("Product!STRING:0|Active!DEC:1|Version!STRING:0\nwowf|1|1.60.1.12345\n")
        self.addons = self.game / "_forever_/Interface/AddOns"
        self.baselines = self.root / "基準"
        self.backups = self.root / "備份"
        self.pkg = u.Package("sample", "測試插件", "Sample", "official/test", "", ("Sample_Options",))
        self.custom = self.root / "customizations"
        self.custom.mkdir()
        self.custom_patch = patch.object(u, "CUSTOMIZATIONS", self.custom)
        self.custom_patch.start()

    def tearDown(self):
        self.custom_patch.stop()
        self.temp.cleanup()

    def archive(self, version="1.0", extra=None, interface="16001", dep=""):
        contents = {}
        for folder in self.pkg.managed_folders:
            contents[f"{folder}/{folder}.toc"] = f"## Interface: {interface}\n## Version: {version}\n## Dependencies: {dep}\nmain.lua\n".encode()
            contents[f"{folder}/main.lua"] = b'local label = "English"\nlocal value = 1\n'
        contents.update(extra or {})
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in contents.items():
                # Repeated fixture builds must not look like author repacks
                # merely because the wall clock crossed a ZIP timestamp tick.
                z.writestr(zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0)),
                           data, compress_type=zipfile.ZIP_DEFLATED)
        raw = stream.getvalue()
        return raw, u.Release(version, "https://example.invalid/official.zip", len(raw), "sha256:" + hashlib.sha256(raw).hexdigest())

    def run_sample(self, apply, raw, release, running=lambda: False):
        rows = []
        with patch.object(u, "PACKAGES", (self.pkg,)), patch.object(u, "fetch", return_value=raw), \
                patch.object(u, "find_release", return_value=release):
            result = u.run_updates(apply, lambda *r: rows.append(r), game=self.game,
                                   baselines=self.baselines, backups=self.backups, running=running)
        return result, rows

    def test_folder_forms_and_wrong_client(self):
        for path in (self.game, self.game / "_forever_", self.addons, self.addons.parent):
            self.assertEqual(u.resolve_game(path), self.game)
        (self.game / ".build.info").write_text("Product|Active|Version\nwow|1|12.0.0.100\n")
        with self.assertRaises(u.SkipUpdate): u.resolve_game(self.game)

    def test_check_empty_client_has_no_writes(self):
        raw, release = self.archive()
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result, rows = self.run_sample(False, raw, release)
        self.assertEqual(result, (0, 2, 0))  # sample + bundled hub
        self.assertIn("可安裝", rows[0][-1])
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_new_install_downloads_complete_package_and_keeps_zip(self):
        raw, release = self.archive()
        result, rows = self.run_sample(True, raw, release)
        self.assertEqual(result[0], 1)
        self.assertEqual((self.baselines / "sample-1.0.zip").read_bytes(), raw)
        self.assertTrue((self.addons / 'Sample_Options/main.lua').is_file())
        self.assertIn('已安裝', rows[0][-1])

    def test_running_game_refused_before_any_write(self):
        raw, release = self.archive()
        with self.assertRaises(u.SkipUpdate): self.run_sample(True, raw, release, lambda: True)
        self.assertFalse(self.addons.exists())
        self.assertFalse(self.baselines.exists())

    def test_bad_archive_and_dependency_refused(self):
        for options in ({'interface': '110000'}, {'dep': 'MissingDependency'}, {'extra': {'../escape.txt': b'evil'}}):
            raw, release = self.archive(**options)
            result, rows = self.run_sample(True, raw, release)
            self.assertEqual(result[0], 0)
            self.assertFalse((self.addons / 'Sample').exists())

    def test_existing_customization_survives_update_without_git(self):
        raw, release = self.archive()
        self.run_sample(True, raw, release)
        changed = self.addons / 'Sample/main.lua'
        changed.write_bytes(b'local label = "Traditional Chinese"\nlocal value = 1\n')
        fresh, rel = self.archive('1.1', {'Sample/main.lua': b'local label = "English"\nlocal value = 2\n'})
        with patch.object(u.shutil, 'which', return_value=None):
            result, rows = self.run_sample(True, fresh, rel)
        self.assertEqual(result[0], 1, rows)
        self.assertEqual(changed.read_bytes(), b'local label = "Traditional Chinese"\nlocal value = 2\n')

    def test_success_deletes_only_this_updates_replaced_files(self):
        raw, release = self.archive()
        self.run_sample(True, raw, release)
        history = self.backups / 'older-backup'
        history.mkdir()
        (history / 'keep.lua').write_bytes(b'retain old history')
        other = self.baselines / 'other-1.0.zip'
        other.write_bytes(b'unrelated archive')
        fresh, rel = self.archive('1.1')

        result, rows = self.run_sample(True, fresh, rel)

        self.assertEqual(result[0], 1, rows)
        self.assertIn('舊版已刪除', rows[0][-1])
        self.assertEqual(u.installed_version(self.addons, self.pkg), '1.1')
        self.assertFalse((self.baselines / 'sample-1.0.zip').exists())
        self.assertEqual((self.baselines / 'sample-1.1.zip').read_bytes(), fresh)
        self.assertEqual(list(self.backups.iterdir()), [history])
        self.assertEqual((history / 'keep.lua').read_bytes(), b'retain old history')
        self.assertEqual(other.read_bytes(), b'unrelated archive')

    def test_cleanup_rejects_a_directory_outside_the_expected_parent(self):
        self.backups.mkdir()
        other = self.root / 'outside'
        other.mkdir()
        child = other / 'file'
        child.write_bytes(b'keep')
        with self.assertRaises(OSError):
            u.delete_replaced_file(other, self.backups, directory=True)
        self.assertEqual(child.read_bytes(), b'keep')

    def test_conflict_preserves_live_plugin(self):
        raw, release = self.archive()
        self.run_sample(True, raw, release)
        changed = self.addons / 'Sample/main.lua'
        changed.write_bytes(b'local label = "My label"\nlocal value = 1\n')
        fresh, rel = self.archive('1.1', {'Sample/main.lua': b'local label = "New upstream label"\nlocal value = 1\n'})
        with patch.object(u.shutil, 'which', return_value=None): result, rows = self.run_sample(True, fresh, rel)
        self.assertEqual(result[0], 0, rows)
        self.assertIn('衝突', rows[0][-1])
        self.assertIn(b'My label', changed.read_bytes())

    def test_install_failure_rolls_back_new_and_old_folders(self):
        raw, release = self.archive()
        self.run_sample(True, raw, release)
        before = u.read_live(self.addons, self.pkg.managed_folders)
        fresh, rel = self.archive('1.1')
        original_rename = Path.rename
        def fail_one(path, target):
            if path.name == 'Sample_Options' and path.parent.name == 'new': raise OSError('simulated failure')
            return original_rename(path, target)
        with patch.object(Path, 'rename', fail_one): result, rows = self.run_sample(True, fresh, rel)
        self.assertEqual(result[0], 0)
        self.assertEqual(u.read_live(self.addons, self.pkg.managed_folders), before)
        self.assertEqual((self.baselines / 'sample-1.0.zip').read_bytes(), raw)

    def test_same_version_can_fill_missing_modules(self):
        raw, release = self.archive()
        self.run_sample(True, raw, release)
        # Move just one module aside to simulate a partially installed package.
        (self.addons / 'Sample_Options').rename(self.root / 'module-off')
        with patch.object(u, 'delete_replaced_file'): result, rows = self.run_sample(True, raw, release)
        self.assertEqual(result[0], 1, rows)
        self.assertTrue((self.addons / 'Sample_Options/main.lua').is_file())
        self.assertTrue((self.baselines / 'sample-1.0.zip').is_file())

    def test_no_baseline_same_version_is_recovered_without_overwrite(self):
        raw, release = self.archive()
        self.run_sample(True, raw, release)
        (self.baselines / 'sample-1.0.zip').rename(self.root / 'archive-off.zip')
        (self.addons / 'Sample/main.lua').write_bytes(b'local personal = true\n')
        with patch.object(u, 'delete_replaced_file'): result, rows = self.run_sample(True, raw, release)
        self.assertEqual(result[0], 1, rows)
        self.assertEqual((self.addons / 'Sample/main.lua').read_bytes(), b'local personal = true\n')
        self.assertEqual((self.baselines / 'sample-1.0.zip').read_bytes(), raw)

    def test_different_clients_have_separate_baselines_and_settings(self):
        other = self.game.with_name('另一個遊戲')
        self.assertNotEqual(u.baseline_location(self.game), u.baseline_location(other))
        settings = self.root / 'settings.json'
        u.remember_game(self.game, settings)
        self.assertEqual(u.remembered_game(settings), self.game)

    def test_excluded_addons_not_planned(self):
        names = {p.anchor for p in u.PACKAGES}
        self.assertTrue(names.isdisjoint({'RXPGuides', 'AmobiCompanion', 'ForeverQuestPins'}))

    def test_newer_local_version_is_not_downgraded_by_stale_author_metadata(self):
        raw, release = self.archive('1.1')
        self.run_sample(True, raw, release)
        before = u.read_live(self.addons, self.pkg.managed_folders)
        old, older_release = self.archive('1.0')
        result, rows = self.run_sample(True, old, older_release)
        self.assertEqual(result[0], 0)
        self.assertEqual(rows[0][-1], '保留較新本機版本')
        self.assertEqual(u.read_live(self.addons, self.pkg.managed_folders), before)

    def test_windows_duplicated_cr_does_not_block_localized_version_update(self):
        base=b'## Title: Test\n## Notes: Original\n## Version: 1.0\n'
        local=base.replace(b'## Notes:',b'## Title-zhTW: Localized\n## Notes:').replace(
            b'## Version:',b'## Notes-zhTW: Localized notes\n## Version:').replace(b'\n',b'\r\r\n')
        fresh=base.replace(b'1.0',b'1.1').replace(b'\n',b'\r\n')
        result=u.merge_text(base,local,fresh,self.root,'Sample/Sample.toc')
        self.assertIn(b'## Title-zhTW: Localized',result)
        self.assertIn(b'## Version: 1.1',result)
        self.assertNotIn(b'\r\r\n',result)


class EmbeddedForeverCoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = InstallTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.pkg = next(pkg for pkg in u.PACKAGES if pkg.key == 'shortest')

    def embedded_archive(self, *, missing_script=None, declare_scripts=True):
        anchor = self.fixture.pkg.anchor
        scripts = ('Core/Loader.lua', 'Begin.lua', 'Core.lua', 'End.lua')
        toc = '## Interface: 16001\n## Version: 1.43.9\n## X-Forever-Core-Embed: 1\nmain.lua\n'
        if declare_scripts:
            toc += ''.join(f'Libs/ForeverCore/{script}\n' for script in scripts)
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr(f'{anchor}/{anchor}.toc', toc)
            archive.writestr(f'{anchor}/main.lua', 'return true\n')
            for script in scripts:
                if script != missing_script:
                    archive.writestr(f'{anchor}/Libs/ForeverCore/{script}', 'return true\n')
        raw = stream.getvalue()
        return raw, u.Release('1.43.9', 'https://example.invalid/new.zip', len(raw))

    def test_fresh_install_needs_no_standalone_core_and_rechecks_cleanly(self):
        f = self.fixture
        raw, release = self.embedded_archive()
        result, rows = f.run_sample(True, raw, release)
        self.assertEqual(result[0], 1, rows)
        self.assertFalse((f.addons/'ForeverCore').exists())
        self.assertEqual((f.baselines/'shortest-1.43.9.zip').read_bytes(), raw)
        for apply in (False, True):
            result, rows = f.run_sample(apply, raw, release)
            self.assertEqual(result[:2], (0, 1), rows)  # The fixture has no bundled hub.
            self.assertEqual(rows[0][-1], '已是最新')

    def test_legacy_upgrade_leaves_standalone_core_and_its_personal_files(self):
        f = self.fixture
        raw, release = f.archive('1.43.2')
        self.assertEqual(f.run_sample(True, raw, release)[0][0], 1)
        extra = f.addons/'ForeverCore/personal.lua'
        extra.write_bytes(b'return true')
        before = u.read_live(f.addons, ('ForeverCore',))
        raw, release = self.embedded_archive()
        result, rows = f.run_sample(True, raw, release)
        self.assertEqual(result[0], 1, rows)
        self.assertEqual(u.read_live(f.addons, ('ForeverCore',)), before)
        self.assertEqual(u.installed_version(f.addons, f.pkg), '1.43.9')
        self.assertFalse((f.baselines/'shortest-1.43.2.zip').exists())

    def test_incomplete_embedded_core_is_rejected(self):
        f = self.fixture
        for options in ({'missing_script': 'Begin.lua'}, {'declare_scripts': False}):
            with self.subTest(**options):
                raw, release = self.embedded_archive(**options)
                result, rows = f.run_sample(True, raw, release)
                self.assertEqual(result[0], 0, rows)
                self.assertIn('ForeverCore', rows[0][-1])
                self.assertFalse((f.addons/f.pkg.anchor).exists())
                self.assertFalse((f.baselines/'shortest-1.43.9.zip').exists())


class IntegerReleaseTests(unittest.TestCase):
    def test_integer_release_order_and_invalid_versions(self):
        self.assertEqual(u.version_name("v853"), "853")
        self.assertGreater(u.version_order("853"), u.version_order("852"))
        self.assertGreater(u.version_order("346"), u.version_order("345"))
        self.assertEqual(u.version_order("r272"), ((272,), ""))
        for bad in ("853-beta", "../853", "1.2.3.4.5", ""):
            with self.assertRaises(u.SkipUpdate):
                u.version_name(bad)


if __name__ == '__main__':
    unittest.main()
