from pathlib import Path
from unittest.mock import patch
import json
import unittest
from dataclasses import replace
import build_share
import release_tools
import online
import updater as u
import test_updater as fixtures


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.InstallTests()
        self.f.setUp()
        self.f.pkg=replace(self.f.pkg,archive=r'Sample-(\d+\.\d+)\.zip')
        raw, release=self.f.archive()
        self.f.run_sample(True,raw,release)
        hub=self.f.addons/'XiaoHeiAddonHub'
        hub.mkdir()
        (hub/'XiaoHeiAddonHub.toc').write_text('## Interface: 16001\n## Version: 0.1.11\nHub.lua\n')
        (hub/'Hub.lua').write_text('local value = 1\n')

    def tearDown(self):self.f.tearDown()

    def test_rebuilding_removes_no_longer_needed_local_patch(self):
        target=self.f.addons/'Sample/main.lua'
        original=target.read_bytes()
        target.write_bytes(original.replace(b'English',b'Chinese'))
        output=self.f.root/'bundle'
        with patch.object(u,'PACKAGES',(self.f.pkg,)):
            build_share.build_customizations(self.f.addons,self.f.baselines,output)
            self.assertTrue((output/'sample/local.zip').is_file())
            target.write_bytes(original)
            build_share.build_customizations(self.f.addons,self.f.baselines,output)
        self.assertFalse((output/'sample/local.zip').exists(),'Stale translation must not be published again')
        self.assertEqual(json.loads((output/'manifest.json').read_text()),{})

    def test_failed_build_leaves_previous_complete_bundle_unchanged(self):
        output=self.f.root/'bundle'
        with patch.object(u,'PACKAGES',(self.f.pkg,)):
            build_share.build_customizations(self.f.addons,self.f.baselines,output)
            before={p.relative_to(output):p.read_bytes() for p in output.rglob('*') if p.is_file()}
            target=self.f.addons/'Sample/main.lua'
            target.write_bytes(target.read_bytes().replace(b'English',b'New translation'))
            missing=u.Package('missing','Missing','Missing','official/test','x')
            with patch.object(u,'PACKAGES',(self.f.pkg,missing)), self.assertRaises(Exception):
                build_share.build_customizations(self.f.addons,self.f.baselines,output)
        self.assertEqual(before,{p.relative_to(output):p.read_bytes() for p in output.rglob('*') if p.is_file()})

    def test_catalog_only_does_not_require_everyone_to_upgrade_ui(self):
        bundle=self.f.root/'bundle'
        with patch.object(u,'PACKAGES',(self.f.pkg,)):
            build_share.build_customizations(self.f.addons,self.f.baselines,bundle)
            with patch.object(u,'CUSTOMIZATIONS',bundle),patch.object(online,'APP_VERSION','9.0.0'):
                output=self.f.root/'catalog-release'
                release_tools.prepare(output,None,catalog_only=True)
        catalog=json.loads((output/'catalog.json').read_text(encoding='utf-8'))
        self.assertEqual(catalog['minimum_app'],'1.1.0')
        self.assertFalse((output/'XiaoHeiForeverUpdater.exe').exists())

    def test_wrong_executable_version_cannot_be_published(self):
        output=self.f.root/'bad-release'
        with patch.object(release_tools,'embedded_version',return_value='1.0.0'):
            with self.assertRaises(u.SkipUpdate):release_tools.prepare(output,Path('old.exe'))
        self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
