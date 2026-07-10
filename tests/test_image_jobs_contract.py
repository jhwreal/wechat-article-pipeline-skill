import copy, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'wechat-article-pipeline' / 'scripts'))
from image_jobs_contract import *

class ContractTests(unittest.TestCase):
    def test_v1_normalizes(self):
        p={'article_slug':'demo','jobs':[{'name':'cover','output':'cover.png','role':'cover','generation_task':{'prompt':'make cover'}}], 'must_avoid':['x']}
        n=normalize_image_jobs(p)
        self.assertEqual(n['schema_version'],2); self.assertEqual(n['slots'][0]['output'],'cover.png'); self.assertEqual(n['generation_queue'][0]['generation_prompt'],'make cover')
        self.assertEqual(p['jobs'][0]['name'],'cover')
    def test_safety_and_queue(self):
        base={'kind':'wechat-image-jobs','schema_version':2,'article':{},'rules':{},'review_defaults':{},'slots':[{'name':'a','output':'x.png'}],'generation_queue':[{'slot':'a','output':'x.png','generation_prompt':'p'}]}
        self.assertEqual(validate_image_jobs(base)['slots'][0]['name'],'a')
        bad=copy.deepcopy(base); bad['slots'][0]['output']='../x.png'
        with self.assertRaises(ValueError): validate_image_jobs(bad)
    def test_missing_filters_by_output(self):
        p={'jobs':[{'name':'body-1','output':'diagram.webp'},{'name':'cover','output':'cover.png'}]}
        n=filter_missing_image_jobs(p, lambda x:x=='diagram.webp')
        self.assertEqual([s['name'] for s in n['slots']],['cover'])
    def test_no_image(self):
        n=normalize_image_jobs({'kind':'wechat-image-jobs','schema_version':2,'article':{},'rules':{},'review_defaults':{},'slots':[],'generation_queue':[]})
        self.assertEqual(n['slots'],[])

    def test_historical_variants_collapse_deterministically(self):
        p={'article_slug':'demo','jobs':[{'name':'body-1','output':'final.png',
            'variants':[{'prompt':'first candidate'},{'prompt':'second candidate'}]}]}
        n=normalize_image_jobs(p)
        self.assertEqual(len(n['slots']),1)
        self.assertEqual(n['generation_queue'][0]['generation_prompt'],'first candidate')

    def test_normalization_is_idempotent_and_does_not_mutate(self):
        p={'article_slug':'demo','jobs':[{'name':'cover','output':'cover.png','prompt':'p'}]}
        original=copy.deepcopy(p)
        n=normalize_image_jobs(p)
        self.assertEqual(normalize_image_jobs(n), n)
        self.assertEqual(p, original)

if __name__=='__main__': unittest.main()
