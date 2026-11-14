from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import notices as n
import online as o
import updater as u


class NoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.game=self.root/'game';self.pkg=u.PACKAGES[0]
        self.notice=n.Notice('a'*64,'1.2.2','2026.11.14',(self.pkg,),{'id':'batch-one','changes':['改善更新流程'],'descriptions':{self.pkg.key:'中文用途'}})
        self.app_patch=patch.object(u,'APP',self.root);self.app_patch.start()
        self.base_patch=patch.object(u,'baseline_location',return_value=self.root/'base');self.base_patch.start()

    def tearDown(self):
        self.app_patch.stop();self.base_patch.stop();self.tmp.cleanup()

    def test_receipt_is_once_per_batch_client_and_program_version(self):
        key=n.receipt_key(self.game,self.notice)
        self.assertFalse(n.seen(key));n.acknowledge(key);self.assertTrue(n.seen(key))
        self.assertFalse(n.seen(n.receipt_key(self.root/'other',self.notice)))
        self.assertFalse(n.seen(n.receipt_key(self.game,self.notice,{'version':'9.0.0'})))
        self.assertEqual(json.loads((self.root/'notice-state.json').read_text()),[key])

    def test_pending_respects_installation_and_successful_state_without_writes(self):
        self.assertTrue(n.pending(self.notice,self.game));self.assertFalse((self.root/'base').exists())
        (self.game/'_forever_/Interface/AddOns'/self.pkg.anchor).mkdir(parents=True)
        base=self.root/'base';base.mkdir()
        (base/'.catalog-state.json').write_text(json.dumps({self.pkg.key:self.notice.identity,'hub':self.notice.identity}))
        self.assertFalse(n.pending(self.notice,self.game))
        text=n.body(self.notice,self.game)
        self.assertIn('已同步',text);self.assertNotIn('可新增的插件',text)

    def test_missing_addon_has_chinese_purpose_and_required_program_guidance(self):
        self.assertIn('中文用途',n.body(self.notice,self.game))
        with patch.object(o,'APP_VERSION','1.0.0'):
            self.assertIn('需要先更新管理器程式',n.body(self.notice,self.game))

    def test_startup_can_describe_future_catalog_but_install_still_rejects(self):
        data={'schema':1,'revision':'future','minimum_app':'99.0.0','packages':[asdict(self.pkg)],'customizations':{'name':'customizations.zip','sha256':'0'*64},'news':self.notice.news}
        raw=json.dumps(data).encode()
        with patch.object(o,'release',return_value={}),patch.object(o,'asset',return_value={}),patch.object(o,'download',return_value=raw):
            result=n.discover()
        self.assertEqual(result.minimum_app,'99.0.0')
        with self.assertRaises(u.SkipUpdate):o.parse_catalog(raw)
        self.assertFalse((self.game/'_forever_').exists())

    def test_malformed_or_oversized_news_is_rejected(self):
        for invalid in ([],{'id':'a','changes':['x'*301],'descriptions':{}},{'id':'a','changes':[],'descriptions':{'unknown':'x'}}):
            with self.assertRaises(u.SkipUpdate):n.validate_news(invalid,(self.pkg,))
        self.assertEqual(n.validate_news(None,(self.pkg,)),{})

    def test_missing_optional_news_is_compatible_with_existing_catalog(self):
        data={'schema':1,'revision':'old','minimum_app':'1.2.2','packages':[asdict(self.pkg)],'customizations':{'name':'customizations.zip','sha256':'0'*64}}
        with patch.object(o,'release',return_value={}),patch.object(o,'asset',return_value={}),patch.object(o,'download',return_value=json.dumps(data).encode()):
            self.assertEqual(n.discover().news,{})

    def test_offline_cached_notice_uses_verified_catalog_and_keeps_news(self):
        catalog=o.Catalog((self.pkg,),self.root/'snapshot/customizations',self.notice.identity,'cached')
        catalog.customizations.parent.mkdir()
        raw=json.dumps({'schema':1,'revision':'cached','minimum_app':'1.2.2','packages':[asdict(self.pkg)],'customizations':{'name':'customizations.zip','sha256':'0'*64},'news':self.notice.news})
        (catalog.customizations.parent/'catalog.json').write_text(raw)
        cache=self.root/'cache';cache.mkdir();(cache/'active.txt').write_text(self.notice.identity)
        with patch.object(o,'CACHE',cache),patch.object(o,'_cached',return_value=catalog) as verify:
            self.assertEqual(n.cached().news,self.notice.news);verify.assert_called_once_with(self.notice.identity)


if __name__=='__main__':unittest.main()
