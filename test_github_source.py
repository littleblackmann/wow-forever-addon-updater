import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import github_source as g


class GitHubSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name)
        self.repo = 'official/sample'
        self.digest = 'sha256:'+'a'*64
        self.url = 'https://github.com/official/sample/releases/download/1.1/Sample-1.1.zip'
        self.data = {'tag_name':'1.1','draft':False,'prerelease':False,'assets':[
            {'name':'Sample-1.1.zip','size':25,'browser_download_url':self.url,'digest':self.digest}]}
        self.page = b'<include-fragment src="/official/sample/releases/expanded_assets/1.1"></include-fragment>'
        self.assets = ('<ul><li><a href="/official/sample/releases/download/1.1/Sample-1.1.zip">zip</a>'
                       f'<clipboard-copy value="{self.digest}"></clipboard-copy></li></ul>').encode()

    def tearDown(self):
        self.temp.cleanup()

    def rate_error(self):
        return HTTPError('https://api.github.com/repos/official/sample/releases/latest',403,'limit',
                         {'X-RateLimit-Remaining':'0','X-RateLimit-Reset':'9999999999'},None)

    def test_fresh_verified_metadata_cache_avoids_duplicate_api_calls(self):
        fetch = Mock(return_value=json.dumps(self.data).encode())
        head = Mock()
        for _ in range(3):
            self.assertEqual(g.release_data(self.repo,'latest',fetch,head,self.cache)['tag_name'],'1.1')
        self.assertEqual(fetch.call_count,1)
        head.assert_not_called()

    def test_rate_limit_uses_official_page_digest_and_head_size(self):
        fetch = Mock(side_effect=[self.rate_error(),self.page,self.assets])
        head = Mock(return_value=25)
        result = g.release_data(self.repo,'latest',fetch,head,self.cache)
        self.assertEqual(result['assets'][0]['digest'],self.digest)
        self.assertEqual(result['assets'][0]['size'],25)
        self.assertEqual(result['_retrieved_via'],'official release page')
        head.assert_called_once_with(self.url)
        self.assertTrue((self.cache/'api-cooldown.json').is_file())

    def test_cooldown_survives_restart_and_does_not_request_exhausted_api(self):
        (self.cache/'api-cooldown.json').write_text(json.dumps({'until':g.time.time()+300}))
        fetch = Mock(side_effect=[self.page,self.assets])
        g.release_data(self.repo,'latest',fetch,Mock(return_value=25),self.cache)
        self.assertTrue(all(call.args[0].startswith('https://github.com/') for call in fetch.call_args_list))

    def test_unrelated_403_is_not_treated_as_quota(self):
        fetch = Mock(side_effect=HTTPError('https://api.github.com/example',403,'forbidden',{},None))
        with self.assertRaises(HTTPError):
            g.release_data(self.repo,'latest',fetch,Mock(),self.cache)
        self.assertEqual(fetch.call_count,1)

    def test_untrusted_fragment_or_wrong_repository_asset_is_rejected(self):
        for index, (page, assets) in enumerate([(b'<include-fragment src="https://evil.invalid/releases/expanded_assets/1.1">',self.assets),
                             (self.page,b'<li><a href="/evil/repo/releases/download/1.1/Sample-1.1.zip">zip</a></li>')]):
            fetch=Mock(side_effect=[self.rate_error(),page,assets])
            with self.assertRaises(ValueError):
                g.release_data(self.repo,'latest',fetch,Mock(return_value=25),self.cache/str(index))

    def test_malformed_cache_does_not_override_official_metadata(self):
        key=g.hashlib.sha256((self.repo+'|latest|None').encode()).hexdigest()
        (self.cache/(key+'.json')).write_text(json.dumps({'saved':'bad','data':self.data}))
        fetch=Mock(return_value=json.dumps(self.data).encode())
        self.assertEqual(g.release_data(self.repo,'latest',fetch,Mock(),self.cache)['tag_name'],'1.1')
        self.assertEqual(fetch.call_count,1)

    def test_historical_rate_fallback_requires_exact_tag_and_stable_release(self):
        fetch=Mock(side_effect=[self.rate_error(),self.page,self.assets])
        result=g.release_data(self.repo,'?per_page=100&page=1',fetch,Mock(return_value=25),self.cache,'1.1')
        self.assertEqual(result[0]['tag_name'],'1.1')
        self.assertIn('/releases/tag/1.1',fetch.call_args_list[1].args[0])

    def test_web_prerelease_is_not_offered_as_stable(self):
        fetch=Mock(side_effect=[self.rate_error(),b'<span class="Label Label--warning">Pre-release</span>'+self.page])
        with self.assertRaises(ValueError):
            g.release_data(self.repo,'latest',fetch,Mock(),self.cache)


if __name__=='__main__':
    unittest.main()
