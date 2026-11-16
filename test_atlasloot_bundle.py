"""Regression checks for the shipped AtlasLoot localization and migration history."""
import re
import unittest
import zipfile
import updater as u


class AtlasLootBundleTests(unittest.TestCase):
    def test_141_translation_keeps_all_author_data_and_existing_names(self):
        package=next(p for p in u.PACKAGES if p.key=='atlasloot')
        base=u.read_zip(u.CUSTOMIZATIONS/'atlasloot/base.zip',package.managed_folders)
        local=u.read_zip(u.CUSTOMIZATIONS/'atlasloot/local.zip',package.managed_folders)
        key='atlaslootclassic_dungeonsandraids/data.lua'
        original=u.normalized_text(base[key][1]);translated=u.normalized_text(local[key][1])
        wrapper=r'ForeverName\("([^"\n]*)", "([^"\n]*)"\)'
        self.assertEqual(len(re.findall(wrapper,translated)),103)
        restored=re.sub(wrapper,lambda m:'"'+m[1]+'"',translated)
        restored=re.sub(r'-- Local Traditional Chinese translations; keep English for other clients\.\nlocal function ForeverName\(en, zhTW\)\n.*?\nend\n\n','',restored,flags=re.S)
        self.assertEqual(restored,original,'Translation must preserve all new author items and classifications')
        for label in ('永恆地城','永恆團隊','族長之廳','海加爾山'):
            self.assertIn(label,translated)

    def test_known_historical_patches_remain_available_for_old_managers(self):
        with zipfile.ZipFile(u.CUSTOMIZATIONS/'history.zip') as history:
            self.assertIsNone(history.testzip())
            for version in ('1.3.7','1.3.8','1.3.9','1.4.1'):
                for label in ('base','local'):
                    self.assertIn(f'atlasloot-{version}/{label}.zip',history.namelist())
            self.assertIn('hub-0.1.11/hub.zip',history.namelist())


if __name__=='__main__':unittest.main()
