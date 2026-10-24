"""Explicit repair routing; private files only, no producer, Node or database.

Original MapBuilder reuse is exercised with its existing protocol fixture.
Changed-route tests use the real source normalizer and spy only on the two
expensive builder boundaries; they are routing, not native-render acceptance.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog_web_materialize as materialize
from anki_pipeline import study_compiled_build as shared
from anki_pipeline import study_compiled_preparation as preparation
from anki_pipeline import study_compiled_repair as repair
from anki_pipeline import study_compiled_resume as resume
from tests import test_study_compiled_preparation as preparation_fixtures
from tests import test_study_compiled_resume as cache_fixtures


class RepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.counter = 0

    def plan(self, changed=(), transform=None):
        value = {'schema': repair.SCHEMA, 'sources': preparation.source_pins(),
                 'dependencies': shared.CompiledBuild._dependencies(),
                 'changed': list(changed)}
        if transform:
            transform(value)
        self.counter += 1
        path = self.root / ('plan-' + str(self.counter) + '.json')
        raw = shared._json(value)
        path.write_bytes(raw)
        return {'path': str(path), 'sha256': shared._sha(raw)}

    def original(self):
        helper = cache_fixtures.CacheTests()
        helper.root = self.root
        fixture = helper.fixture()
        cache = helper.cache([fixture[6]], fixture[7])
        self.addCleanup(cache.close)
        return fixture, cache

    def normalized(self):
        self.counter += 1
        root = self.root / ('normalized-book-' + str(self.counter))
        root.mkdir()
        for name in ('media', 'cards', 'evidence'):
            (root / name).mkdir()
        fixture = preparation_fixtures.PreparationTests()
        fixture.root = root
        wrapper_raw, base_raw = fixture.fixture(True)
        base_value = json.loads(base_raw)
        # These bytes are an explicit routing fixture, not a native module.
        base_value['modules'] = {'routing-fixture': {'src': 'module.js'}}
        base_raw = shared._json(base_value)
        current_raw, proof = preparation.normalize_artifact(base_raw, wrapper_raw,
            materialize.ReadOnlyMedia(root / 'media'))
        self.assertIsNotNone(proof)
        wrapper = {'path': 'cards/card.html', 'sha256': shared._sha(wrapper_raw)}
        base = {'path': 'evidence/base.json', 'sha256': shared._sha(base_raw)}
        current = {'path': 'evidence/current.json', 'sha256': shared._sha(current_raw)}
        for descriptor, raw in ((wrapper, wrapper_raw), (base, base_raw), (current, current_raw)):
            (root / descriptor['path']).write_bytes(raw)
        selected = {'identity': 'subject:normalized', 'base_artifact': base, 'artifact': current}
        return root, wrapper, selected

    def empty_cache(self):
        path = self.root / 'empty-cache.json'
        raw = shared._json({'schema': 'study-complete-result-cache.v1', 'files': [],
                            'completed_semantic': {}})
        path.write_bytes(raw)
        cache = resume.ResultCache({'path': str(path), 'sha256': shared._sha(raw)})
        self.addCleanup(cache.close)
        return cache

    def builder(self, cache, plan, **options):
        self.counter += 1
        builder = repair.RepairBuilder(cache, self.root / ('store-' + str(self.counter)),
                                      plan=plan, **options)
        self.addCleanup(lambda: builder.close(complete=False))
        return builder

    def invoke(self, builder, fixture):
        return builder.build(fixture[0], fixture[1], fixture[2], identity=fixture[3],
                             policy=fixture[4], source_url=fixture[5])

    def changed_build(self, builder, fixture):
        root, wrapper, selected = fixture
        return builder.build(root, wrapper, selected['artifact'], identity=selected['identity'],
                             policy={'external': {}, 'inline': []},
                             source_url='https://study.test/subject/index.html')

    def produced(self, builder, identity):
        evidence = builder.builder.store.put(b'{"proof":"complete"}', 'json')
        record = builder.builder.store.put(shared._json({'evidence': {'proof': evidence}}), 'json')
        html = builder.builder.store.put(b'<p>original bilingual content</p>', 'html')
        return {'mode': 'compiled', 'identity': identity, 'record': record,
                'resources': {'https://study.test/html': builder.builder.store.descriptor(html)}}

    def many_resources(self, builder, identity):
        result = self.produced(builder, identity)
        result['resources'] = {}
        for index in range(258):
            asset = builder.builder.store.put(('complete resource ' + str(index)).encode(), 'html')
            result['resources']['https://study.test/' + str(index)] = builder.builder.store.descriptor(asset)
        return result

    def test_unlisted_valid_cache_uses_original_mapper_and_never_producer(self):
        fixture, cache = self.original()
        builder = self.builder(cache, self.plan())
        with patch.object(builder.builder, 'build', side_effect=AssertionError('producer forbidden')):
            self.assertEqual(self.invoke(builder, fixture), fixture[6]['result'])
        builder.close()
        self.assertEqual(builder.report()['repaired'], 0)

    def test_unlisted_missing_or_stale_cache_rejects_without_fallback(self):
        fixture, cache = self.original()
        for kind in ('missing', 'stale'):
            with self.subTest(kind=kind):
                changed = list(fixture)
                if kind == 'missing':
                    changed[3] = 'subject:uncached'
                else:
                    changed[4] = {'external': {'changed.js': '0' * 64}, 'inline': []}
                builder = self.builder(cache, self.plan())
                with patch.object(builder.builder, 'build', side_effect=AssertionError('producer forbidden')):
                    with self.assertRaises((KeyError, ValueError)):
                        self.invoke(builder, changed)
                builder.close(complete=False)
                with self.assertRaises(ValueError):
                    builder.report()

    def test_default_mapper_rejects_normalized_key_and_no_implicit_repair(self):
        fixture, cache = self.original()
        value = json.loads((fixture[0] / fixture[2]['path']).read_bytes())
        value['field_script_normalization'] = {'schema': 'not-an-approved-repair'}
        raw = shared._json(value)
        descriptor = {'path': 'evidence/changed.json', 'sha256': shared._sha(raw)}
        (fixture[0] / descriptor['path']).write_bytes(raw)
        changed = list(fixture)
        changed[2] = descriptor
        with self.assertRaisesRegex(ValueError, 'cache key'):
            self.invoke(resume.MapBuilder(cache), changed)

    def test_explicit_changed_real_normalization_orders_base_before_producer_and_logs_once(self):
        fixture = self.normalized()
        builder = self.builder(self.empty_cache(), self.plan([fixture[2]]))
        events = []
        result = self.produced(builder, fixture[2]['identity'])
        def base(*args, **kwargs):
            self.assertEqual(args[2], fixture[2]['base_artifact'])
            events.append('base-qualified')
        def produce(*args, **kwargs):
            self.assertEqual(events[-1], 'base-qualified')
            self.assertEqual(args[2], fixture[2]['artifact'])
            self.assertNotIn('completed_semantic', kwargs)
            events.append('producer')
            return copy.deepcopy(result)
        with patch.object(builder.mapper, 'build', side_effect=base), \
                patch.object(builder.builder, 'build', side_effect=produce):
            self.assertEqual(self.changed_build(builder, fixture), result)
            self.assertEqual(self.changed_build(builder, fixture), result)
        builder.close()
        report = builder.report()
        rows = Path(report['results']['path']).read_bytes().splitlines()
        self.assertEqual(len(rows), 1)
        row = json.loads(rows[0])
        self.assertEqual(row['base_artifact'], fixture[2]['base_artifact'])
        self.assertEqual(row['artifact'], fixture[2]['artifact'])
        self.assertEqual(row['repair_plan_sha256'], report['plan']['sha256'])
        self.assertEqual(report['repaired'], 1)

    def test_approved_change_still_requires_complete_original_cache(self):
        fixture = self.normalized()
        builder = self.builder(self.empty_cache(), self.plan([fixture[2]]))
        with patch.object(builder.builder, 'build', side_effect=AssertionError('producer forbidden')):
            with self.assertRaisesRegex(KeyError, 'no qualified'):
                self.changed_build(builder, fixture)

    def test_normalized_tampering_rehashed_into_plan_is_rejected_before_producer(self):
        for kind in ('proof', 'side', 'wrapper'):
            with self.subTest(kind=kind):
                # Separate source roots keep each authenticated fixture isolated.
                fixture = self.normalized()
                root, wrapper, selected = fixture
                value = json.loads((root / selected['artifact']['path']).read_bytes())
                if kind == 'proof':
                    value['field_script_normalization']['base_artifact_sha256'] = '0' * 64
                elif kind == 'side':
                    value['sides'][1]['html'] += '<p>unauthorized content</p>'
                else:
                    wrapper_raw = (root / wrapper['path']).read_bytes() + b' '
                    (root / wrapper['path']).write_bytes(wrapper_raw)
                    wrapper['sha256'] = shared._sha(wrapper_raw)
                raw = shared._json(value)
                (root / selected['artifact']['path']).write_bytes(raw)
                selected['artifact']['sha256'] = shared._sha(raw)
                builder = self.builder(self.empty_cache(), self.plan([selected]))
                with patch.object(builder.mapper, 'build'), \
                        patch.object(builder.builder, 'build', side_effect=AssertionError('producer forbidden')):
                    with self.assertRaisesRegex(ValueError, 'normalization|bound'):
                        self.changed_build(builder, fixture)
                builder.close(complete=False)

    def test_external_plan_pin_authorities_duplicate_and_paths_are_strict(self):
        cache = self.empty_cache()
        fixture = self.normalized()
        mutations = [lambda v: v.update(schema='other'),
                     lambda v: v['sources'].update(normalizer_sha256='0' * 64),
                     lambda v: v['dependencies'].update(unapproved='0' * 64),
                     lambda v: v['changed'].append(copy.deepcopy(v['changed'][0])),
                     lambda v: v['changed'][0]['artifact'].update(path='../outside.json')]
        for change in mutations:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.builder(cache, self.plan([copy.deepcopy(fixture[2])], change))
        descriptor = self.plan()
        descriptor['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA'):
            self.builder(cache, descriptor)

    def test_changed_descriptor_and_exact_coverage_required(self):
        fixture = self.normalized()
        cache = self.empty_cache()
        builder = self.builder(cache, self.plan([fixture[2]]))
        with self.assertRaisesRegex(ValueError, 'exact approved changed set'):
            builder.close()
        with self.assertRaises(ValueError):
            builder.report()
        builder = self.builder(cache, self.plan([fixture[2]]))
        altered = copy.deepcopy(fixture)
        altered[2]['artifact']['path'] = 'evidence/not-approved.json'
        with patch.object(builder.mapper, 'build', side_effect=AssertionError('base must not run')):
            with self.assertRaisesRegex(ValueError, 'approved identity'):
                self.changed_build(builder, altered)

    def test_shared_final_receipts_cover_new_resources_record_and_all_evidence(self):
        fixture = self.normalized()
        receipts = resume._Receipts()
        builder = self.builder(self.empty_cache(), self.plan([fixture[2]]), receipts=receipts)
        result = self.produced(builder, fixture[2]['identity'])
        with patch.object(builder.mapper, 'build'), patch.object(builder.builder, 'build', return_value=result):
            self.changed_build(builder, fixture)
        builder.close()
        assets = builder.builder.store.assets
        record = json.loads((assets / result['record']['src']).read_bytes())
        paths = [Path(next(iter(result['resources'].values()))['path']),
                 assets / result['record']['src'], assets / record['evidence']['proof']['src']]
        for path in paths:
            self.assertIn(str(path), receipts.items)
        media_paths = list((fixture[0] / 'media').iterdir())
        self.assertTrue(media_paths)
        for path in media_paths:
            self.assertIn(str(path.resolve()), receipts.items)
        # Simulate a later book mutating an earlier new resource after close.
        paths[2].write_bytes(b'later book changed earlier evidence')
        with self.assertRaisesRegex(ValueError, 'SHA|changed'):
            receipts.check()

    def test_final_receipts_reject_later_change_to_authenticated_expansion_media(self):
        fixture = self.normalized()
        receipts = resume._Receipts()
        builder = self.builder(self.empty_cache(), self.plan([fixture[2]]), receipts=receipts)
        result = self.produced(builder, fixture[2]['identity'])
        with patch.object(builder.mapper, 'build'), patch.object(builder.builder, 'build', return_value=result):
            self.changed_build(builder, fixture)
        builder.close()
        next((fixture[0] / 'media').iterdir()).write_bytes(b'changed source registration')
        with self.assertRaisesRegex(ValueError, 'SHA|changed'):
            receipts.check()

    def test_many_owned_resources_use_bounded_batches_without_rebasing(self):
        fixture = self.normalized()
        builder = self.builder(self.empty_cache(), self.plan([fixture[2]]))
        result = self.many_resources(builder, fixture[2]['identity'])
        existing = next(iter(result['resources'].values()))
        builder.receipts.read(existing['path'], existing['sha256'])
        original = copy.deepcopy(builder.receipts.items[existing['path']])
        events, batches, descriptors = [], [], []
        publish, authority = builder.receipts.publish_new_owned, builder._authority

        def checked_authority():
            events.append('authority')
            authority()

        def checked_publish(directory, fd, outputs):
            events.append('publish')
            batches.append(dict(outputs))
            descriptors.append(fd)
            self.assertEqual(builder._directory_identity(os.fstat(fd)), builder.owned_directories[directory])
            publish(directory, fd, outputs)

        with patch.object(builder.mapper, 'build'), patch.object(builder.builder, 'build', return_value=result), \
                patch.object(builder, '_authority', side_effect=checked_authority), \
                patch.object(builder.receipts, 'publish_new_owned', side_effect=checked_publish):
            self.assertEqual(self.changed_build(builder, fixture), result)
        self.assertEqual([len(batch) for batch in batches], [1, 256, 2])
        self.assertEqual(descriptors[-2], descriptors[-1])
        for index, event in enumerate(events):
            if event == 'publish':
                self.assertEqual(events[index - 1:index + 2], ['authority', 'publish', 'authority'])
        self.assertTrue(all(Path(existing['path']).name not in batch for batch in batches))
        self.assertEqual(builder.receipts.items[existing['path']], original)
        builder.close()
        self.assertEqual(builder.report()['repaired'], 1)
        self.assertEqual(len(builder.log_path.read_bytes().splitlines()), 1)
        builder.receipts.check()

    def test_later_publication_batch_failure_never_logs_success(self):
        fixture = self.normalized()
        builder = self.builder(self.empty_cache(), self.plan([fixture[2]]))
        result = self.many_resources(builder, fixture[2]['identity'])
        existing = next(iter(result['resources'].values()))
        builder.receipts.read(existing['path'], existing['sha256'])
        original = copy.deepcopy(builder.receipts.items[existing['path']])
        last = list(result['resources'].values())[-1]
        original_last = Path(last['path']).read_bytes()
        last['sha256'] = '0' * 64
        with patch.object(builder.mapper, 'build'), patch.object(builder.builder, 'build', return_value=result), \
                patch.object(builder.receipts, 'publish_new_owned', wraps=builder.receipts.publish_new_owned) as publish:
            with self.assertRaisesRegex(ValueError, 'external SHA'):
                self.changed_build(builder, fixture)
            self.assertEqual([len(call.args[2]) for call in publish.call_args_list], [1, 256, 2])
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                self.changed_build(builder, fixture)
        self.assertTrue(builder.failed)
        self.assertEqual(builder.seen, {})
        self.assertEqual(builder.completed, set())
        self.assertEqual(builder.log_bytes, 0)
        self.assertEqual(builder.log_path.read_bytes(), b'')
        self.assertEqual(builder.receipts.items[existing['path']], original)
        self.assertIn(list(result['resources'].values())[255]['path'], builder.receipts.items)
        self.assertNotIn(last['path'], builder.receipts.items)
        self.assertEqual(Path(last['path']).read_bytes(), original_last)
        builder.close(complete=False)
        with self.assertRaises(ValueError):
            builder.report()

    def test_unlisted_authored_keeps_original_validator_without_worker(self):
        root = self.root / 'authored'
        root.mkdir()
        for name in ('cards', 'media', 'evidence'):
            (root / name).mkdir()
        fixture = preparation_fixtures.PreparationTests()
        fixture.root = root
        wrapper_raw, artifact_raw = fixture.fixture(False)
        wrapper = {'path': 'cards/card.html', 'sha256': shared._sha(wrapper_raw)}
        artifact = {'path': 'evidence/card.json', 'sha256': shared._sha(artifact_raw)}
        (root / wrapper['path']).write_bytes(wrapper_raw)
        (root / artifact['path']).write_bytes(artifact_raw)
        builder = self.builder(self.empty_cache(), self.plan())
        with patch.object(builder.builder, '_run', side_effect=AssertionError('worker forbidden')):
            result = builder.build(root, wrapper, artifact, identity='other:authored',
                                   policy={'external': {}, 'inline': []},
                                   source_url='https://study.test/other/index.html')
        self.assertEqual(result['mode'], 'authored')
        self.assertIsNone(builder.builder.worker)
        builder.close()

    def test_failed_producer_never_logs_success_or_attempts_fallback(self):
        fixture = self.normalized()
        builder = self.builder(self.empty_cache(), self.plan([fixture[2]]))
        with patch.object(builder.mapper, 'build') as mapper, \
                patch.object(builder.builder, 'build', side_effect=RuntimeError('original producer failed')) as producer:
            with self.assertRaisesRegex(RuntimeError, 'original producer failed'):
                self.changed_build(builder, fixture)
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                self.changed_build(builder, fixture)
        self.assertEqual(mapper.call_count, 1)
        self.assertEqual(producer.call_count, 1)
        builder.close(complete=False)
        self.assertEqual(builder.log_path.read_bytes(), b'')
        with self.assertRaises(ValueError):
            builder.report()


if __name__ == '__main__':
    unittest.main()
