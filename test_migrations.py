from pathlib import Path
from io import BytesIO
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import updater as u


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


if __name__ == '__main__': unittest.main()
