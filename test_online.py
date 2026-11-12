from dataclasses import asdict, replace
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import online as o
import updater as u
import self_update
import test_updater as fixtures


class OnlineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.InstallTests()
        self.fixture.setUp()
        self.f = self.fixture
        self.f.pkg = replace(self.f.pkg, archive=r'Sample-(\d+\.\d+)\.zip')
        self.cache_patch = patch.object(o, 'CACHE', self.f.root / 'online')
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.fixture.tearDown()

    def bundle(self, revision, label=b'Chinese one', hub_comment=b''):
        raw, _ = self.f.archive()
        with zipfile.ZipFile(BytesIO(raw)) as z:
            original = z.read('Sample/main.lua')
        inner = {}
        for name, contents in [('base', original), ('local', original.replace(b'English', label))]:
            buf = BytesIO()
            with zipfile.ZipFile(buf, 'w') as z: z.writestr('Sample/main.lua', contents)
            inner[f'customizations/sample/{name}.zip'] = buf.getvalue()
        hub_buf = BytesIO()
        # Minimal complete hub fixture, intentionally no dependency on the live game.
        with zipfile.ZipFile(hub_buf, 'w') as z:
            z.writestr('XiaoHeiAddonHub/XiaoHeiAddonHub.toc', b'## Interface: 16001\n## Version: 0.1.11\nHub.lua\n')
            z.writestr('XiaoHeiAddonHub/Hub.lua', b'local value = 1\n' + hub_comment)
        inner['customizations/hub.zip'] = hub_buf.getvalue()
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            for name, contents in inner.items(): z.writestr(name, contents)
        payload = stream.getvalue()
        manifest = json.dumps({'schema': 1, 'revision': revision, 'minimum_app': '1.1.0',
                               'packages': [asdict(self.f.pkg)],
                               'customizations': {'name': 'customizations.zip', 'sha256': hashlib.sha256(payload).hexdigest()}}).encode()
        docs = {'catalog.json': manifest, 'customizations.zip': payload}
        release = {'tag_name': 'catalog', 'assets': [
            {'name': name, 'size': len(contents), 'digest': 'sha256:' + hashlib.sha256(contents).hexdigest(),
             'browser_download_url': f'https://github.com/{o.REPOSITORY}/releases/download/catalog/{name}'}
            for name, contents in docs.items()]}
        return docs, release

    def sync(self, revision='one', label=b'Chinese one', hub_comment=b''):
        docs, release = self.bundle(revision, label, hub_comment)
        def fetch(url, limit): return docs[url.rsplit('/', 1)[1]]
        with patch.object(o, 'release', return_value=release), patch.object(u, 'fetch', side_effect=fetch):
            result = o.sync_catalog()
        self.assertIsNotNone(result.identity, result.note)
        return result

    def install(self, catalog):
        raw, release = self.f.archive()
        rows = []
        with patch.object(u, 'find_release', return_value=release), patch.object(u, 'fetch', return_value=raw), \
                patch.object(u, 'recycle_completed_file'):
            result = u.run_updates(True, lambda *row: rows.append(row), game=self.f.game,
                                   backups=self.f.backups, baselines=self.f.baselines,
                                   running=lambda: False, catalog=catalog)
        return result, rows

    def test_verified_catalog_and_offline_cached_fallback(self):
        first = self.sync()
        with patch.object(o, 'release', side_effect=OSError('offline')):
            offline = o.sync_catalog()
        self.assertEqual(first.identity, offline.identity)
        self.assertIn('離線', offline.note)
        self.assertEqual(offline.packages[0].anchor, 'Sample')

    def test_bad_download_does_not_replace_last_good_catalog(self):
        good = self.sync()
        docs, release = self.bundle('two')
        with patch.object(o, 'release', return_value=release), \
                patch.object(u, 'fetch', side_effect=lambda url, _: docs['catalog.json'] if url.endswith('catalog.json') else b'corrupt'):
            result = o.sync_catalog()
        self.assertEqual(result.identity, good.identity)
        self.assertEqual((o.CACHE / 'active.txt').read_text(), good.identity)

    def test_tampered_cache_falls_back_to_embedded(self):
        good = self.sync()
        (good.customizations / 'hub.zip').write_bytes(b'changed')
        with patch.object(o, 'release', side_effect=OSError('offline')):
            result = o.sync_catalog()
        self.assertIsNone(result.identity)

    def test_manifest_rejects_path_escape_excluded_and_incompatible_version(self):
        docs, _ = self.bundle('one')
        data = json.loads(docs['catalog.json'])
        for anchor in ('../escape', 'ForeverQuestPins', 'Sample/Other'):
            data['packages'][0]['anchor'] = anchor
            with self.assertRaises(u.SkipUpdate): o.parse_catalog(json.dumps(data).encode())
        data['packages'][0]['anchor'] = 'Sample'
        data['minimum_app'] = '99.0.0'
        with self.assertRaises(u.SkipUpdate): o.parse_catalog(json.dumps(data).encode())

    def test_new_translation_and_hub_update_preserve_personal_changes(self):
        one = self.sync()
        result, rows = self.install(one)
        self.assertEqual(result, (2, 2, 0), rows)
        target = self.f.addons / 'Sample/main.lua'
        target.write_bytes(target.read_bytes().replace(b'value = 1', b'value = 9'))
        two = self.sync('two', b'Chinese two', b'-- new hub feature\n')
        with patch.object(u.shutil, 'which', return_value=None):
            result, rows = self.install(two)
        self.assertEqual(result, (2, 2, 0), rows)
        self.assertEqual(target.read_bytes(), b'local label = "Chinese two"\nlocal value = 9\n')
        self.assertIn(b'new hub feature', (self.f.addons / 'XiaoHeiAddonHub/Hub.lua').read_bytes())
        result, rows = self.install(two)
        self.assertEqual(result, (0, 0, 0), rows)

    def test_catalog_conflict_keeps_old_state_and_live_file(self):
        one = self.sync()
        self.install(one)
        target = self.f.addons / 'Sample/main.lua'
        target.write_bytes(target.read_bytes().replace(b'Chinese one', b'My own label'))
        two = self.sync('two', b'Chinese two')
        result, rows = self.install(two)
        self.assertIn('衝突', rows[0][-1])
        self.assertIn(b'My own label', target.read_bytes())
        state = json.loads((self.f.baselines / '.catalog-state.json').read_text())
        self.assertEqual(state['sample'], one.identity)

    def test_app_version_check_and_download_validation(self):
        data = {'tag_name': 'v1.2.0', 'assets': [{'name': 'XiaoHeiForeverUpdater.exe', 'size': 10,
                'browser_download_url': f'https://github.com/{o.REPOSITORY}/releases/download/v1.2.0/XiaoHeiForeverUpdater.exe',
                'digest': 'sha256:' + hashlib.sha256(b'MZnew app!').hexdigest()}]}
        with patch.object(o, 'release', return_value=data): info = o.check_app()
        with patch.object(u, 'APP', self.f.root), patch.object(u, 'fetch', return_value=b'MZnew app!'):
            downloaded = o.download_app(info)
        self.assertEqual(downloaded.read_bytes(), b'MZnew app!')
        with patch.object(u, 'APP', self.f.root), patch.object(u, 'fetch', return_value=b'MZchanged!'):
            with self.assertRaises(u.SkipUpdate): o.download_app(info)
        data['assets'][0]['browser_download_url'] = 'https://github.com/other/repo/download/app.exe'
        with patch.object(o, 'release', return_value=data):
            with self.assertRaises(u.SkipUpdate): o.check_app()

    def test_self_update_only_schedules_verified_local_exe(self):
        folder = self.f.root / '.updates'
        folder.mkdir()
        path = folder / 'new.exe'
        path.write_bytes(b'MZtest')
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with patch.object(u, 'APP', self.f.root), patch.object(self_update.subprocess, 'Popen') as launch:
            self_update.schedule(path, sha)
            self.assertEqual(launch.call_args.kwargs['env']['XIAOHEI_UPDATE_STAGED'], str(path))
            with self.assertRaises(u.SkipUpdate): self_update.schedule(path, '0' * 64)
            with self.assertRaises(u.SkipUpdate): self_update.schedule(self.f.root / 'outside.exe', sha)
        self.assertEqual(launch.call_count, 1)


if __name__ == '__main__':
    unittest.main()
