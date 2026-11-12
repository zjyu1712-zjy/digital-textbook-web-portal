"""Synthetic review records exercise integrity, not academic review quality."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import independent_audit as audit
from test_review_audit import sample


def source_read(course, inventory, plan, reviewer='fixture-independent-context'):
    packet = audit.review_packet(course, inventory, plan)
    observations = []
    for row in packet['samples']:
        observations.append({'sampleId': row['sampleId'], 'sourceId': row['sourceId'],
                             'locator': row['locator'],
                             'expectedPoints': ['Synthetic source observation for ' + row['sampleId']],
                             'evidence': 'Synthetic fixture evidence at ' + row['locator']})
    return {'reviewerId': reviewer, 'contextMode': audit.CONTEXT_MODE,
            'packetFingerprint': packet['packetFingerprint'], 'observations': observations}


def reviewed(course=None, inventory=None):
    if course is None:
        course, inventory = sample()
    plan = audit.create_plan(course, inventory, 'fixture-producer')
    read = source_read(course, inventory, plan)
    packet = audit.review_packet(course, inventory, plan, 'compare', read)
    records = []
    for row in packet['samples']:
        checks = {aspect: 'pass' for aspect in audit.ASPECTS}
        if row['reviewMode'] == 'reference':
            checks.update(summary='not-applicable', emphasis='not-applicable')
        records.append({'sampleId': row['sampleId'], 'reviewerId': read['reviewerId'],
                        'contextMode': audit.CONTEXT_MODE, 'planFingerprint': plan['planFingerprint'],
                        'sampleFingerprint': row['sampleFingerprint'],
                        'sourceReadFingerprint': packet['sourceReadFingerprint'],
                        'result': 'pass', 'checks': checks,
                        'evidence': 'Synthetic explicit comparison for ' + row['sampleId'], 'issues': []})
    course['independentReview'] = {'plan': plan, 'sourceRead': read, 'records': records}
    return course, inventory


class PlanTests(unittest.TestCase):
    def test_comparison_includes_common_exam_conditions_and_changes_expire_it(self):
        course, inventory = sample()
        question = {'id': 'exam-q', 'version': '1', 'chapterIds': ['ch1'],
                    'sourceRefs': [{'sourceId': 's1', 'locator': 'p8'}],
                    'prompt': [{'type': 'paragraph', 'text': 'Apply the common conditions.'}],
                    'parts': [{'id': 'a', 'fields': [{'id': 'x', 'kind': 'number'}]}],
                    'answer': {'version': '1', 'blocks': [{'type': 'paragraph', 'text': '2'}]}}
        course['questions'] = [question]
        course['exams'] = [{'id': 'paper', 'title': 'Synthetic exam', 'questionIds': ['exam-q'],
                            'instructions': [{'type': 'paragraph', 'text': 'Use exactly two observations.'}],
                            'sourceRefs': [{'sourceId': 's1', 'locator': 'p1/common'}]}]
        inventory['items'].append({'id': 'exam-item', 'sourceId': 's1', 'locator': 'p8', 'kind': 'exam'})
        course['coverage'].append({'sourceItemId': 'exam-item', 'targets': ['exam-q'], 'status': 'covered'})
        course, inventory = reviewed(course, inventory)
        data = course['independentReview']
        packet = audit.review_packet(course, inventory, data['plan'], 'compare', data['sourceRead'])
        selected = next(r for r in packet['samples'] if r['sampleId'] == 'exam-item')
        self.assertEqual(selected['examContext'], course['exams'])
        source = audit.review_packet(course, inventory, data['plan'], 'source')
        self.assertNotIn('Use exactly two observations.', json.dumps(source))
        course['exams'][0]['instructions'][0]['text'] = 'Use exactly three observations.'
        self.assertEqual(audit.audit_independent(course, inventory)['status'], 'stale')

    def test_plan_is_deterministic_and_does_not_modify_input(self):
        course, inventory = sample()
        before = copy.deepcopy((course, inventory))
        plan = audit.create_plan(course, inventory, 'producer')
        self.assertEqual(plan, audit.create_plan(course, inventory, 'producer'))
        self.assertEqual(before, (course, inventory))
        self.assertNotIn('result', json.dumps(plan))
        self.assertEqual({tuple(x['chapterIds']) for x in plan['samples']}, {('ch1',), ('ch2',)})

    def test_teaching_questions_and_sources_get_separate_strata(self):
        course, inventory = sample()
        for number, kind, source in [(3, 'exercise', 's1'), (4, 'lesson', 's2')]:
            item_id = 'i' + str(number)
            inventory['items'].append({'id': item_id, 'sourceId': source, 'kind': kind,
                                       'locator': 'p' + str(number), 'expectedParts': []})
            course['coverage'].append({'sourceItemId': item_id, 'targets': ['k1'], 'status': 'covered'})
            course['learningMap'].append({'sourceItemId': item_id, 'disposition': 'integrated',
                'explanationTargets': ['k1'], 'summaryTargets': [], 'emphasisTargets': [],
                'summaryNote': 'Small teaching fixture.', 'emphasisNote': 'Fixture.', 'evidence': 'Fixture.'})
        plan = audit.create_plan(course, inventory, 'producer')
        self.assertEqual({row['sampleId'] for row in plan['samples']}, {'i1', 'i2', 'i3', 'i4'})
        self.assertEqual({row['kindGroup'] for row in plan['samples']}, {'teaching', 'question'})

    def test_unmapped_items_are_mandatory_and_use_source_scope(self):
        course, inventory = sample()
        inventory['items'].append({'id': 'lost', 'sourceId': 's1', 'locator': 'p9', 'kind': 'lesson'})
        plan = audit.create_plan(course, inventory, 'producer')
        lost = next(row for row in plan['samples'] if row['sampleId'] == 'lost')
        self.assertEqual(lost['reviewMode'], 'unmapped')
        self.assertEqual(lost['chapterIds'], ['ch1'])
        self.assertEqual(lost['chapterBasis'], 'source-scope')
        self.assertEqual(plan['candidateCount'], 3)

    def test_unassigned_items_remain_visible(self):
        course, inventory = sample()
        course['taskContract']['sourceUses'] = []
        inventory['items'].append({'id': 'lost', 'sourceId': 's1', 'locator': 'p9', 'kind': 'lesson'})
        plan = audit.create_plan(course, inventory, 'producer')
        row = next(row for row in plan['samples'] if row['sampleId'] == 'lost')
        self.assertEqual(row['chapterIds'], [])
        self.assertEqual(row['chapterBasis'], 'unassigned')

    def test_extra_samples_only_expand_deterministic_selection(self):
        course, inventory = sample()
        for n in range(3, 9):
            item_id = 'i' + str(n)
            inventory['items'].append({'id': item_id, 'sourceId': 's1', 'locator': 'p' + str(n), 'kind': 'lesson'})
            course['coverage'].append({'sourceItemId': item_id, 'targets': ['k1'], 'status': 'covered'})
        base = audit.create_plan(course, inventory, 'producer')
        selected = {x['sampleId'] for x in base['samples']}
        extra = next(x['id'] for x in inventory['items'] if x['id'] not in selected)
        extended = audit.create_plan(course, inventory, 'producer', extra_item_ids=[extra])
        self.assertEqual({x['sampleId'] for x in extended['samples']}, selected | {extra})

    def test_selection_cannot_be_shrunk_or_reseeded(self):
        for mutation in [lambda p: p['samples'].pop(), lambda p: p.update(minimumPerGroup=0),
                         lambda p: p.update(planFingerprint='0' * 64),
                         lambda p: p.update(algorithm='choose-easy-items')]:
            course, inventory = reviewed()
            mutation(course['independentReview']['plan'])
            self.assertEqual(audit.audit_independent(course, inventory)['status'], 'invalid')

    def test_bad_configuration_and_unknown_extra_are_rejected(self):
        course, inventory = sample()
        for kwargs in [{'producer_id': ''}, {'producer_id': 'x', 'minimum_per_group': True},
                       {'producer_id': 'x', 'minimum_per_group': 0},
                       {'producer_id': 'x', 'extra_item_ids': ['unknown']},
                       {'producer_id': 'x', 'extra_item_ids': ['i1', 'i1']}]:
            with self.assertRaises(ValueError):
                audit.create_plan(course, inventory, **kwargs)


class PacketTests(unittest.TestCase):
    def test_source_packet_hides_generation_and_existing_verdicts(self):
        course, inventory = sample()
        course['semanticReviews'] = [{'evidence': 'SECRET_REVIEW_PASS', 'result': 'pass'}]
        course['learningMap'][0]['evidence'] = 'SECRET_INTEGRATION_CLAIM'
        inventory['items'][0]['answer'] = 'SECRET_INVENTORY_ANSWER'
        course['acceptance'] = [{'text': 'SECRET_ACCEPTANCE_PASS'}]
        plan = audit.create_plan(course, inventory, 'producer')
        packet = audit.review_packet(course, inventory, plan)
        encoded = json.dumps(packet)
        for hidden in ['SECRET_REVIEW_PASS', 'SECRET_INTEGRATION_CLAIM', 'SECRET_INVENTORY_ANSWER',
                       'SECRET_ACCEPTANCE_PASS', course['chapters'][0]['sections'][0]['blocks'][0]['text']]:
            self.assertNotIn(hidden, encoded)
        self.assertEqual(packet['phase'], 'source')

    def test_comparison_requires_complete_source_observations(self):
        course, inventory = sample()
        plan = audit.create_plan(course, inventory, 'producer')
        with self.assertRaises(ValueError):
            audit.review_packet(course, inventory, plan, 'compare')
        read = source_read(course, inventory, plan)
        read['observations'].pop()
        with self.assertRaises(ValueError):
            audit.review_packet(course, inventory, plan, 'compare', read)

    def test_same_declared_producer_or_inherited_context_is_rejected(self):
        course, inventory = sample()
        plan = audit.create_plan(course, inventory, 'producer')
        for change in [{'reviewerId': 'producer'}, {'contextMode': 'reuse-generation-context'}]:
            read = source_read(course, inventory, plan)
            read.update(change)
            with self.assertRaises(ValueError):
                audit.review_packet(course, inventory, plan, 'compare', read)

    def test_read_requires_locator_and_concrete_expected_points(self):
        course, inventory = sample()
        plan = audit.create_plan(course, inventory, 'producer')
        for change in [{'expectedPoints': []}, {'evidence': ''}, {'locator': 'different-page'},
                       {'sourceId': 'another-source'}, {'sampleId': 'unknown'}]:
            read = source_read(course, inventory, plan)
            read['observations'][0].update(change)
            with self.assertRaises(ValueError):
                audit.review_packet(course, inventory, plan, 'compare', read)

    def test_compare_contains_actual_content_without_author_pass_claims(self):
        course, inventory = sample()
        course['learningMap'][0]['evidence'] = 'DO_NOT_TRUST_AUTHOR_CLAIM'
        plan = audit.create_plan(course, inventory, 'producer')
        read = source_read(course, inventory, plan)
        packet = audit.review_packet(course, inventory, plan, 'compare', read)
        encoded = json.dumps(packet)
        self.assertIn(course['chapters'][0]['sections'][0]['blocks'][0]['text'], encoded)
        self.assertNotIn('DO_NOT_TRUST_AUTHOR_CLAIM', encoded)
        self.assertEqual(packet['sourceReadFingerprint'], audit._digest(read))

    def test_per_sample_packets_bind_to_whole_packet_and_aggregate_read(self):
        course, inventory = sample()
        plan = audit.create_plan(course, inventory, 'producer')
        full = audit.review_packet(course, inventory, plan)
        read = source_read(course, inventory, plan)
        for observation in read['observations']:
            packet = audit.review_packet(course, inventory, plan, sample_id=observation['sampleId'])
            self.assertEqual(packet['parentPacketFingerprint'], full['packetFingerprint'])
            self.assertEqual(len(packet['samples']), 1)
            self.assertEqual(len(packet['sourceItems']), 1)
            observation['packetFingerprint'] = packet['packetFingerprint']
        packet = audit.review_packet(course, inventory, plan, 'compare', read, sample_id='i1')
        self.assertEqual([r['sampleId'] for r in packet['sourceRead']['observations']], ['i1'])
        read['observations'][0]['packetFingerprint'] = '0' * 64
        with self.assertRaises(ValueError):
            audit.review_packet(course, inventory, plan, 'compare', read)


class AuditTests(unittest.TestCase):
    def test_absent_legacy_is_unreviewed_not_structure_failure(self):
        for schema in [1, 2]:
            course, inventory = sample()
            course['schemaVersion'] = schema
            report = audit.audit_independent(course, inventory)
            self.assertEqual(report['status'], 'not-reviewed')
            self.assertEqual(report['errors'], [])
            self.assertFalse(report['complete'])
            self.assertTrue(all(row['status'] == 'not-reviewed' for row in report['chapters']))
            self.assertTrue(audit.audit_independent(course, inventory, required=True)['errors'])

    def test_required_flag_is_typed_and_incomplete_review_blocks_completion(self):
        course, inventory = reviewed()
        course['independentReview']['required'] = True
        course['independentReview']['records'] = []
        report = audit.audit_independent(course, inventory)
        self.assertTrue(report['required'])
        self.assertTrue(report['errors'])
        for bad in [0, 1, 'false', None, []]:
            course['independentReview']['required'] = bad
            self.assertEqual(audit.audit_independent(course, inventory)['status'], 'invalid')

    def test_current_complete_samples_are_not_a_whole_book_pass(self):
        course, inventory = reviewed()
        before = copy.deepcopy((course, inventory))
        report = audit.audit_independent(course, inventory)
        self.assertEqual(report['status'], 'sampled-pass')
        self.assertEqual(report['selectedCount'], 2)
        self.assertEqual(report['reviewedCount'], 2)
        self.assertTrue(report['complete'])
        self.assertTrue(all(row['status'] == 'sampled-pass' for row in report['chapters']))
        self.assertEqual(before, (course, inventory))
        self.assertIn('不代表全文', report['assurance'])

    def test_missing_sample_does_not_pass(self):
        course, inventory = reviewed()
        course['independentReview']['records'].pop()
        report = audit.audit_independent(course, inventory)
        self.assertEqual(report['status'], 'not-reviewed')
        self.assertEqual(report['reviewedCount'], 1)

    def test_source_only_is_not_a_review_pass(self):
        course, inventory = reviewed()
        course['independentReview']['records'] = []
        report = audit.audit_independent(course, inventory)
        self.assertEqual(report['status'], 'not-reviewed')
        self.assertEqual(report['reviewedCount'], 0)

    def test_changed_target_stales_only_affected_samples(self):
        course, inventory = reviewed()
        course['chapters'][0]['sections'][0]['blocks'][0]['text'] = 'Changed content.'
        report = audit.audit_independent(course, inventory)
        self.assertEqual(report['status'], 'stale')
        self.assertEqual({r['chapterId']: r['status'] for r in report['chapters']},
                         {'ch1': 'stale', 'ch2': 'sampled-pass'})

    def test_source_contract_inventory_and_mapping_changes_stale_plan(self):
        changes = [lambda c, i: c['sources'][0].update(sha256='changed'),
                   lambda c, i: c['taskContract'].update(goal='changed requirement'),
                   lambda c, i: i['items'][0].update(locator='different page'),
                   lambda c, i: c['coverage'][0]['targets'].pop()]
        for mutation in changes:
            course, inventory = reviewed()
            mutation(course, inventory)
            self.assertEqual(audit.audit_independent(course, inventory)['status'], 'stale')

    def test_changed_source_observation_invalidates_comparison_records(self):
        course, inventory = reviewed()
        course['independentReview']['sourceRead']['observations'][0]['expectedPoints'].append('A new condition.')
        self.assertEqual(audit.audit_independent(course, inventory)['status'], 'stale')

    def test_fail_or_pending_cannot_be_masked_by_later_pass(self):
        for result, state in [('fail', 'failed'), ('pending', 'pending')]:
            course, inventory = reviewed()
            blocker = copy.deepcopy(course['independentReview']['records'][0])
            blocker['result'] = result
            blocker['checks']['summary'] = result
            blocker['issues'] = [{'aspect': 'summary', 'description': 'Synthetic omitted condition.'}]
            course['independentReview']['records'].insert(0, blocker)
            self.assertEqual(audit.audit_independent(course, inventory)['status'], state)

    def test_pass_cannot_hide_findings_or_failing_checks(self):
        for mutation in [lambda r: r['checks'].update(summary='fail'),
                         lambda r: r['issues'].append({'aspect': 'summary', 'description': 'Missing.'}),
                         lambda r: r.update(evidence=''),
                         lambda r: r.update(checks={'sourceFidelity': 'pass'}),
                         lambda r: r.update(reviewerId='another-context')]:
            course, inventory = reviewed()
            mutation(course['independentReview']['records'][0])
            self.assertEqual(audit.audit_independent(course, inventory)['status'], 'invalid')

    def test_reference_use_does_not_require_fabricated_summary_or_emphasis(self):
        course, inventory = sample()
        course['taskContract']['sourceUses'][0]['usage'] = 'reference'
        course, inventory = reviewed(course, inventory)
        self.assertEqual(audit.audit_independent(course, inventory)['status'], 'sampled-pass')
        course['independentReview']['records'][0]['checks']['summary'] = 'pass'
        self.assertEqual(audit.audit_independent(course, inventory)['status'], 'invalid')

    def test_unmapped_sample_cannot_pass(self):
        course, inventory = sample()
        inventory['items'].append({'id': 'lost', 'sourceId': 's1', 'locator': 'p9', 'kind': 'lesson'})
        course, inventory = reviewed(course, inventory)
        report = audit.audit_independent(course, inventory)
        self.assertEqual(report['status'], 'invalid')
        self.assertIn('lost', [r['sampleId'] for r in report['samples']])

    def test_unknown_duplicate_observation_and_malformed_inputs_do_not_crash(self):
        for value in [None, [], 'text', {'plan': []}, {'plan': {}}, {'plan': {'version': 1}}]:
            course, inventory = sample()
            course['independentReview'] = value
            report = audit.audit_independent(course, inventory)
            self.assertIn(report['status'], ('not-reviewed', 'invalid'))
        for mutation in [lambda r: r.update(sampleId='unknown'), lambda r: r.update(issues=[None])]:
            course, inventory = reviewed()
            mutation(course['independentReview']['records'][0])
            self.assertEqual(audit.audit_independent(course, inventory)['status'], 'invalid')

    def test_fresh_rereview_can_supersede_stale_record_but_not_current_fail(self):
        course, inventory = reviewed()
        old = copy.deepcopy(course['independentReview']['records'])
        course['chapters'][0]['sections'][0]['blocks'][0]['text'] = 'New corrected content.'
        reviewed(course, inventory)
        course['independentReview']['records'] = old + course['independentReview']['records']
        self.assertEqual(audit.audit_independent(course, inventory)['status'], 'sampled-pass')


if __name__ == '__main__':
    unittest.main()
