from dataclasses import replace
from io import BytesIO
import json
import unittest
from unittest.mock import patch
import zipfile

import updater as u
import test_updater as fixtures


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.InstallTests()
        self.f.setUp()
        self.old, self.old_release = self.f.archive('1.0')
        self.new, release = self.f.archive('1.1', {'Sample/main.lua': b'local label = "English"\nlocal value = 2\n'})
        self.old_release = replace(self.old_release, url='https://fixture.invalid/old.zip')
        self.new_release = replace(release, url='https://fixture.invalid/new.zip')
        with zipfile.ZipFile(BytesIO(self.old)) as z:
            z.extractall(self.f.addons)
        (self.f.addons/'Sample/main.lua').write_bytes(b'local label = "Chinese"\nlocal value = 1\n')

    def tearDown(self):
        self.f.tearDown()

    def run_update(self, apply=True, old_raw=None, missing=False):
        f = self.f
        rows = []
        def release(pkg, client, version=None):
            if version:
                if missing:
                    raise u.SkipUpdate('author no longer provides old version')
                return self.old_release
            return self.new_release
        def fetch(url, limit):
            return (self.old if old_raw is None else old_raw) if url.endswith('old.zip') else self.new
        with patch.object(u, 'PACKAGES', (f.pkg,)), patch.object(u, 'find_release', side_effect=release) as lookup, \
                patch.object(u, 'fetch', side_effect=fetch), patch.object(u, 'recycle_completed_file'), \
                patch.object(u.shutil, 'which', return_value=None):
            result = u.run_updates(apply, lambda *row: rows.append(row), game=f.game,
                                   backups=f.backups, baselines=f.baselines, running=lambda: False)
        return result, rows, lookup

    def test_fresh_manager_recovers_old_archive_and_keeps_local_changes(self):
        result, rows, lookup = self.run_update()
        self.assertEqual(result[0], 1, rows)
        lookup.assert_any_call(self.f.pkg, '1.60.1', '1.0')
        self.assertEqual((self.f.addons/'Sample/main.lua').read_bytes(), b'local label = "Chinese"\nlocal value = 2\n')
        self.assertEqual((self.f.baselines/'sample-1.1.zip').read_bytes(), self.new)

    def test_unavailable_old_release_keeps_live_files(self):
        before = u.read_live(self.f.addons, self.f.pkg.managed_folders)
        result, rows, _ = self.run_update(missing=True)
        self.assertEqual(result[0], 0, rows)
        self.assertEqual(u.read_live(self.f.addons, self.f.pkg.managed_folders), before)
        self.assertIn('1.0', rows[0][-1])
        self.assertFalse((self.f.baselines/'sample-1.0.zip').exists())

    def test_wrong_old_archive_version_is_not_saved_or_applied(self):
        before = u.read_live(self.f.addons, self.f.pkg.managed_folders)
        wrong, _ = self.f.archive('9.9')
        self.old_release = replace(self.old_release, size=len(wrong), digest='')
        result, rows, _ = self.run_update(old_raw=wrong)
        self.assertEqual(result[0], 0, rows)
        self.assertEqual(u.read_live(self.f.addons, self.f.pkg.managed_folders), before)
        self.assertFalse((self.f.baselines/'sample-1.0.zip').exists())

    def test_check_does_not_download_or_write_old_baseline(self):
        result, rows, lookup = self.run_update(apply=False)
        self.assertEqual(lookup.call_count, 1)
        self.assertFalse(self.f.baselines.exists())
        self.assertIn('補取', rows[0][-1])


class HistoricalSourceTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory()
        self.cache_patch = patch.object(u, 'APP', Path(self.temp.name))
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.temp.cleanup()

    def test_curseforge_selects_exact_stable_version_and_client(self):
        pkg = u.Package('sample', 'Sample', 'Sample', '123/sample', r'Sample-(\d+\.\d+)\.zip')
        def row(ident, version, client='1.60.1', kind='release'):
            return {'id':ident,'name':f'Sample-{version}.zip','type':kind,'versions':[client],
                    'url':f'https://www.curseforge.com/wow/addons/sample/files/{ident}','filesize':25}
        data={'id':123,'urls':{'curseforge':'https://www.curseforge.com/wow/addons/sample'},
              'files':[row(1001,'1.0'),row(1002,'1.1'),row(1003,'1.0','12.0.0'),row(1004,'1.0',kind='beta')]}
        with patch.object(u,'fetch',return_value=json.dumps(data).encode()):
            result=u.find_release(pkg,'1.60.1','1.0')
        self.assertEqual(result.version,'1.0')
        self.assertEqual(result.url,'https://edge.forgecdn.net/files/1/001/Sample-1.0.zip')

    def test_github_historical_pages_selects_exact_stable_asset(self):
        pkg=u.Package('sample','Sample','Sample','official/sample',r'Sample-(\d+\.\d+)\.zip')
        def row(version,draft=False):
            return {'tag_name':version,'draft':draft,'prerelease':False,'assets':[
                {'name':f'Sample-{version}.zip','size':25,
                 'browser_download_url':f'https://github.com/official/sample/releases/download/{version}/Sample-{version}.zip'}]}
        pages=[[row('1.1'),row('1.0',True)],[row('1.0')]]
        with patch.object(u,'fetch',side_effect=[json.dumps(p).encode() for p in pages]):
            result=u.find_release(pkg,'1.60.1','1.0')
        self.assertEqual(result.version,'1.0')
        self.assertIn('/1.0/',result.url)


if __name__ == '__main__':
    unittest.main()
