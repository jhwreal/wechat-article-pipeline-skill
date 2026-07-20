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
        p={'jobs':[{'name':'body-1','output':'diagram.webp','prompt':'diagram'}, {'name':'cover','output':'cover.png','prompt':'cover'}]}
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

    def test_duplicate_queue_task_is_rejected(self):
        payload = {
            'kind': 'wechat-image-jobs',
            'schema_version': 2,
            'article': {},
            'rules': {},
            'review_defaults': {},
            'slots': [
                {'name': 'cover', 'output': 'cover.png'},
                {'name': 'closing', 'output': 'closing.png'},
            ],
            'generation_queue': [
                {'slot': 'cover', 'output': 'cover.png', 'generation_prompt': 'cover'},
                {'slot': 'cover', 'output': 'cover.png', 'generation_prompt': 'duplicate'},
            ],
        }

        with self.assertRaisesRegex(ValueError, 'match slots|unique'):
            validate_image_jobs(payload)

    def test_empty_prompt_is_rejected(self):
        payload = {
            'kind': 'wechat-image-jobs',
            'schema_version': 2,
            'article': {},
            'rules': {},
            'review_defaults': {},
            'slots': [{'name': 'cover', 'output': 'cover.png'}],
            'generation_queue': [
                {'slot': 'cover', 'output': 'cover.png', 'generation_prompt': '   '}
            ],
        }

        with self.assertRaisesRegex(ValueError, 'prompt is empty'):
            validate_image_jobs(payload)

    def test_slot_names_and_output_filenames_are_strict(self):
        base = {
            'kind': 'wechat-image-jobs',
            'schema_version': 2,
            'article': {},
            'rules': {},
            'review_defaults': {},
            'slots': [{'name': 'cover', 'output': 'cover.png'}],
            'generation_queue': [
                {'slot': 'cover', 'output': 'cover.png', 'generation_prompt': 'cover'}
            ],
        }
        for name in ('../cover', 'bad name', ''):
            bad = copy.deepcopy(base)
            bad['slots'][0]['name'] = name
            bad['generation_queue'][0]['slot'] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_image_jobs(bad)
        for output in ('nested/cover.png', r'nested\cover.png', 'cover.txt'):
            bad = copy.deepcopy(base)
            bad['slots'][0]['output'] = output
            bad['generation_queue'][0]['output'] = output
            with self.subTest(output=output), self.assertRaises(ValueError):
                validate_image_jobs(bad)

    def test_outputs_are_portable_across_case_insensitive_and_windows_filesystems(self):
        base = {
            'kind': 'wechat-image-jobs',
            'schema_version': 2,
            'article': {},
            'rules': {},
            'review_defaults': {},
            'slots': [
                {'name': 'first', 'output': 'Cover.png'},
                {'name': 'second', 'output': 'cover.PNG'},
            ],
            'generation_queue': [
                {'slot': 'first', 'output': 'Cover.png', 'generation_prompt': 'first'},
                {'slot': 'second', 'output': 'cover.PNG', 'generation_prompt': 'second'},
            ],
        }
        with self.assertRaisesRegex(ValueError, 'case-insensitively'):
            validate_image_jobs(base)

        reserved = copy.deepcopy(base)
        reserved['slots'] = [{'name': 'first', 'output': 'CON.png'}]
        reserved['generation_queue'] = [
            {'slot': 'first', 'output': 'CON.png', 'generation_prompt': 'first'}
        ]
        with self.assertRaisesRegex(ValueError, 'unsafe output'):
            validate_image_jobs(reserved)

    def test_invalid_rules_digest_and_slot_index_are_rejected(self):
        base = {
            'kind': 'wechat-image-jobs',
            'schema_version': 2,
            'article': {},
            'rules': {'sha256': 'not-a-digest'},
            'review_defaults': {},
            'slots': [{'index': 0, 'name': 'cover', 'output': 'cover.png'}],
            'generation_queue': [
                {'slot': 'cover', 'output': 'cover.png', 'generation_prompt': 'cover'}
            ],
        }
        with self.assertRaisesRegex(ValueError, 'rules.sha256'):
            validate_image_jobs(base)
        base['rules'] = {}
        with self.assertRaisesRegex(ValueError, 'positive integer'):
            validate_image_jobs(base)

    def test_skipped_visuals_are_explicit_body_slots_and_cannot_overlap(self):
        base = {
            'kind': 'wechat-image-jobs',
            'schema_version': 2,
            'article': {'skipped_visuals': ['body-2']},
            'rules': {},
            'review_defaults': {},
            'slots': [{'name': 'cover', 'output': 'cover.png'}],
            'generation_queue': [
                {'slot': 'cover', 'output': 'cover.png', 'generation_prompt': 'cover'}
            ],
        }
        self.assertEqual(validate_image_jobs(base)['article']['skipped_visuals'], ['body-2'])

        overlap = copy.deepcopy(base)
        overlap['article']['skipped_visuals'] = ['cover']
        with self.assertRaisesRegex(ValueError, 'body-N'):
            validate_image_jobs(overlap)

        overlap = copy.deepcopy(base)
        overlap['article']['skipped_visuals'] = ['body-1']
        overlap['slots'].append({'name': 'body-1', 'output': 'body-1.png'})
        overlap['generation_queue'].append(
            {'slot': 'body-1', 'output': 'body-1.png', 'generation_prompt': 'body'}
        )
        with self.assertRaisesRegex(ValueError, 'cannot also appear'):
            validate_image_jobs(overlap)

if __name__=='__main__': unittest.main()
