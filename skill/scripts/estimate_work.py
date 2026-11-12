"""Local workflow estimates and evidence-backed usage summaries; never calls a model."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys


STAGES = ('inventory', 'plan', 'generation', 'review', 'global-review',
          'independent-source', 'independent-compare', 'visual-review')
MAX_PAGES_PER_UNIT = 8
MAX_UNIT_ATTEMPTS = 3
MAX_NETWORK_ATTEMPTS = 3


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(label + ' must be an integer >= ' + str(minimum))
    return value


def _number(value, label):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(label + ' must be a finite nonnegative number')
    return value


def stage_name(value):
    if not isinstance(value, str):
        return 'unknown'
    if value.startswith('unit:'):
        return 'generation'
    prefix = value.split(':', 1)[0]
    return prefix if prefix in STAGES else 'unknown'


def normalize_tokens(value):
    """Recognize provider counters without treating absent usage as zero."""
    result = {'inputTokens': None, 'outputTokens': None, 'totalTokens': None,
              'cachedInputTokens': None, 'issues': []}
    if not isinstance(value, dict):
        return result
    if isinstance(value.get('usage'), dict):
        value = value['usage']
    for target, alternatives in [('inputTokens', ('input_tokens', 'prompt_tokens')),
                                 ('outputTokens', ('output_tokens', 'completion_tokens')),
                                 ('totalTokens', ('total_tokens',))]:
        supplied = [value[key] for key in alternatives if key in value]
        if not supplied:
            continue
        if any(type(v) is not int or v < 0 for v in supplied) or len(set(supplied)) != 1:
            result['issues'].append(target + ': invalid or conflicting provider counters')
        else:
            result[target] = supplied[0]
    if result['inputTokens'] is not None and result['outputTokens'] is not None:
        total = result['inputTokens'] + result['outputTokens']
        if result['totalTokens'] is not None and result['totalTokens'] != total:
            result['issues'].append('totalTokens: disagrees with input plus output')
            result['totalTokens'] = None
        elif not result['issues']:
            result['totalTokens'] = total
    cached = [value[k]['cached_tokens'] for k in ('input_tokens_details', 'prompt_tokens_details')
              if isinstance(value.get(k), dict) and 'cached_tokens' in value[k]]
    if cached:
        if (any(type(v) is not int or v < 0 for v in cached) or len(set(cached)) != 1
                or result['inputTokens'] is None or cached[0] > result['inputTokens']):
            result['issues'].append('cachedInputTokens: invalid or not bounded by known input')
        else:
            result['cachedInputTokens'] = cached[0]
    return result


def _calibration_samples(calibration):
    if calibration is None:
        return {}
    if not isinstance(calibration, dict) or calibration.get('kind') not in ('user-supplied', 'measured'):
        raise ValueError('calibration.kind must be user-supplied or measured')
    if calibration.get('testDouble'):
        raise ValueError('test-double observations cannot calibrate real requests')
    stages = calibration.get('stages')
    if not isinstance(stages, dict) or any(key not in STAGES for key in stages):
        raise ValueError('calibration.stages contains an unknown workflow stage')
    output = {}
    for stage, records in stages.items():
        if not isinstance(records, list) or not records:
            raise ValueError(stage + ': calibration must contain nonempty observations')
        values = {key: [] for key in ('inputTokens', 'outputTokens', 'elapsedSeconds')}
        for record in records:
            if not isinstance(record, dict) or record.get('testDouble'):
                raise ValueError(stage + ': invalid or synthetic calibration observation')
            for key in values:
                if record.get(key) is not None:
                    value = _integer(record[key], key) if key.endswith('Tokens') else _number(record[key], key)
                    values[key].append(value)
        output[stage] = {key: {'low': min(rows), 'high': max(rows), 'sampleCount': len(rows)}
                         if rows else None for key, rows in values.items()}
    return output


def estimate_work(scope, calibration=None, prices=None, confirmed_cache_hits=None, completed_stages=None):
    """Return conditional call bounds for the current portal workflow.

    Missing planning counts have no invented upper bound. Calibrated totals cover
    successful responses; failed HTTP attempts and local processing are separate.
    """
    if not isinstance(scope, dict):
        raise ValueError('scope must be an object')
    pages = _integer(scope.get('pageCount'), 'pageCount', 1)
    included = _integer(scope.get('includedPageCount', pages), 'includedPageCount', 1)
    if included > pages:
        raise ValueError('includedPageCount exceeds pageCount')
    chapters = scope.get('chapterCount')
    if chapters is not None:
        _integer(chapters, 'chapterCount', 1)
    minimum_units = max((included + MAX_PAGES_PER_UNIT - 1) // MAX_PAGES_PER_UNIT, chapters or 1)
    units, samples = scope.get('unitCount'), scope.get('sampleCount')
    if units is not None and _integer(units, 'unitCount', 1) < minimum_units:
        raise ValueError('unitCount cannot cover the included pages/chapters at <=8 pages per unit')
    if samples is not None:
        _integer(samples, 'sampleCount', 1)
    limit = scope.get('maxModelCalls')
    if limit is not None:
        _integer(limit, 'maxModelCalls', 1)
    spent = _integer(scope.get('spentModelCalls', 0), 'spentModelCalls')
    available = None if limit is None else max(0, limit - spent)
    u_low, u_high = (minimum_units, None) if units is None else (units, units)
    s_low, s_high = (1, None) if samples is None else (samples, samples)
    ranges = {'inventory': (pages, pages), 'plan': (1, 1),
              'generation': (u_low, None if u_high is None else u_high * MAX_UNIT_ATTEMPTS),
              'review': (u_low, None if u_high is None else u_high * MAX_UNIT_ATTEMPTS),
              'global-review': (1, 1), 'independent-source': (s_low, s_high),
              'independent-compare': (s_low, s_high), 'visual-review': (1, 1)}
    hits = {} if confirmed_cache_hits is None else confirmed_cache_hits
    if not isinstance(hits, dict) or any(key not in STAGES for key in hits):
        raise ValueError('confirmed_cache_hits contains an unknown workflow stage')
    completed = [] if completed_stages is None else completed_stages
    if (not isinstance(completed, (list, tuple, set)) or any(key not in STAGES for key in completed)
            or len(set(completed)) != len(completed)):
        raise ValueError('completed_stages must contain unique known workflow stages')
    stage_rows = []
    for stage in STAGES:
        full_low, full_high = ranges[stage]
        low, high = (0, 0) if stage in completed else (full_low, full_high)
        count = _integer(hits.get(stage, 0), stage + ' confirmed cache hits')
        if count > low:
            raise ValueError(stage + ': confirmed hits cannot exceed requests guaranteed by the current plan')
        stage_rows.append({'stage': stage, 'completed': stage in completed,
                           'fullLogicalRequests': {'low': full_low, 'high': full_high},
                           'logicalRequests': {'low': low, 'high': high},
                           'confirmedCacheHits': count,
                           'uncachedSuccessfulResponses': {'low': low - count, 'high': None if high is None else high - count}})
    total_low = sum(row['uncachedSuccessfulResponses']['low'] for row in stage_rows)
    highs = [row['uncachedSuccessfulResponses']['high'] for row in stage_rows]
    total_high = sum(highs) if all(value is not None for value in highs) else None
    calibrated = _calibration_samples(calibration)

    def metric(key):
        low, high, missing = 0, 0, []
        for row in stage_rows:
            calls = row['uncachedSuccessfulResponses']
            if calls['high'] == 0:
                continue
            sample = calibrated.get(row['stage'], {}).get(key)
            if sample is None:
                missing.append(row['stage'])
                continue
            low += calls['low'] * sample['low']
            high = None if high is None or calls['high'] is None else high + calls['high'] * sample['high']
        if missing:
            return {'status': 'unknown', 'low': None, 'high': None, 'missingStages': missing}
        return {'status': 'conditional', 'low': low, 'high': high, 'missingStages': []}

    metrics = {key: metric(key) for key in ('inputTokens', 'outputTokens', 'elapsedSeconds')}
    cost = {'status': 'unknown', 'low': None, 'high': None, 'currency': None,
            'reason': 'Explicit input/output prices and complete stage token observations are required.'}
    if prices is not None:
        if not isinstance(prices, dict) or not isinstance(prices.get('currency'), str) or not prices['currency'].strip():
            raise ValueError('prices.currency is required')
        input_price = _number(prices.get('inputPerMillion'), 'inputPerMillion')
        output_price = _number(prices.get('outputPerMillion'), 'outputPerMillion')
        cost['currency'] = prices['currency'].strip()
        if all(metrics[key]['status'] == 'conditional' for key in ('inputTokens', 'outputTokens')):
            cost = {'status': 'conditional', 'currency': prices['currency'].strip(),
                    'low': (metrics['inputTokens']['low'] * input_price + metrics['outputTokens']['low'] * output_price) / 1000000,
                    'high': None, 'reason': 'Assumes the supplied flat input/output prices; no discounts or taxes inferred.'}
            if all(metrics[key]['high'] is not None for key in ('inputTokens', 'outputTokens')):
                cost['high'] = (metrics['inputTokens']['high'] * input_price + metrics['outputTokens']['high'] * output_price) / 1000000
    unknown = [name for name in ('unitCount', 'sampleCount') if scope.get(name) is None]
    return {
        'status': 'bounded' if not unknown else 'partial',
        'scope': {'pageCount': pages, 'includedPageCount': included, 'chapterCount': chapters,
                  'unitCount': units, 'sampleCount': samples},
        'assumptions': {'includedAllPagesWhenNotSpecified': 'includedPageCount' not in scope,
                        'maxPagesPerUnit': MAX_PAGES_PER_UNIT, 'maxUnitAttempts': MAX_UNIT_ATTEMPTS,
                        'maxNetworkAttemptsPerRequest': MAX_NETWORK_ATTEMPTS,
                        'completionConditional': 'Bounds assume readable teaching content and a conversion that succeeds within the configured retry policy.',
                        'sampleLowerBound': 'A completed source-first review has at least one sample; the actual plan determines how many.'},
        'completedStages': [stage for stage in STAGES if stage in completed],
        'estimateScope': 'remaining-stages' if completed else 'whole-workflow',
        'unknownPlanningFields': unknown, 'minimumUnitCount': minimum_units, 'stages': stage_rows,
        'calls': {'successfulResponses': {'low': total_low, 'high': total_high},
                  'networkAttempts': {'low': total_low, 'high': None if total_high is None else total_high * MAX_NETWORK_ATTEMPTS},
                  'maxModelCalls': limit, 'spentModelCalls': spent, 'availableModelCalls': available,
                  'limitAssessment': 'unknown' if available is None else ('below-minimum' if available < total_low else
                      'may-stop-before-worst-case' if total_high is None or available < total_high * MAX_NETWORK_ATTEMPTS else 'covers-count-bound')},
        'calibration': {'status': 'not-calibrated' if calibration is None else 'conditional',
                        'kind': calibration.get('kind') if calibration else None,
                        'basis': calibration.get('basis') if calibration else None},
        'successfulResponseEstimates': {**metrics, 'cost': cost},
        'excludedOverheads': {'failedRequestBilling': 'unknown', 'retryBackoffAndFailedLatency': 'unknown',
                              'extractionBuildBrowserAndQueueSeconds': 'unknown'},
        'notes': ['Call bounds are not duration or token promises. Unknown values are null, never invented zeros.',
                  'Calibrated ranges use observed minima/maxima, not statistical confidence intervals or guaranteed limits.',
                  'Only confirmed exact-key cache hits are deducted; page or chapter completion is not a cache guarantee.',
                  'No model request, price lookup or network operation is performed by this estimator.'],
    }


def usage_baseline(documents):
    """Summarize explicit log documents and build separate real-model calibrations."""
    if not isinstance(documents, list) or not documents:
        raise ValueError('documents must be a nonempty list')
    sources, observations, excluded = [], [], 0
    declared_calls, declared_sources, unclassified = 0, 0, 0
    unknown_attempt_coverage, real_sources = False, 0
    seen_documents = set()
    cache_complete, failed_complete = True, True
    identities = {}
    issues = []
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get('data'), dict):
            raise ValueError('each document requires data and a source label')
        data = document['data']
        source = document.get('source')
        digest = document.get('sha256')
        if not isinstance(source, str) or not source or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('each document requires source and an actual SHA-256 digest')
        if (source, digest) in seen_documents:
            raise ValueError('Duplicate usage document: ' + source)
        seen_documents.add((source, digest))
        records = data.get('usage', [])
        if not isinstance(records, list):
            raise ValueError(source + ': usage must be a list')
        calls = data.get('calls')
        if calls is not None:
            _integer(calls, 'calls')
        if 'testDouble' in data and type(data['testDouble']) is not bool:
            raise ValueError(source + ': testDouble must be boolean')
        synthetic_document = data.get('testDouble') is True
        complete = data.get('formatVersion') == 2
        if not synthetic_document:
            real_sources += 1
            history_complete = complete and data.get('legacyHistoryComplete') is not False
            cache_complete = cache_complete and history_complete
            failed_complete = failed_complete and history_complete
        sources.append({'source': source, 'sha256': digest, 'declaredCalls': calls,
                        'formatVersion': data.get('formatVersion'), 'testDouble': synthetic_document})
        network_entries = 0
        mixed_synthetic = False
        for index, row in enumerate(records):
            if not isinstance(row, dict):
                issues.append({'source': source, 'recordIndex': index, 'issue': 'usage row is not an object'})
                continue
            if 'testDouble' in row and type(row['testDouble']) is not bool:
                raise ValueError(source + ': row testDouble must be boolean')
            if synthetic_document or row.get('testDouble') is True:
                excluded += 1
                mixed_synthetic = True
                continue
            status = row.get('status', 'success' if not complete else None)
            if status not in ('success', 'failed', 'cache-hit'):
                issues.append({'source': source, 'recordIndex': index, 'issue': 'unknown outcome status'})
                continue
            if status != 'cache-hit':
                network_entries += 1
            token = normalize_tokens(row.get('tokens', row.get('usage')))
            seconds = row.get('elapsedSeconds')
            if seconds is not None:
                try:
                    _number(seconds, 'elapsedSeconds')
                except ValueError:
                    issues.append({'source': source, 'recordIndex': index, 'issue': 'invalid elapsedSeconds'})
                    seconds = None
            identity = {key: row.get(key, data.get(key)) for key in ('provider', 'model', 'skillFingerprint')}
            key = json.dumps(identity, sort_keys=True)
            group = identities.setdefault(key, {'identity': identity, 'stages': {}, 'evidence': []})
            stage = stage_name(row.get('stage'))
            observation = {'source': source, 'sourceSHA256': digest, 'recordIndex': index,
                           'stage': stage, 'originalStage': row.get('stage'), 'status': status,
                           'elapsedSeconds': seconds, **token}
            observations.append(observation)
            if token['issues']:
                issues.append({'source': source, 'recordIndex': index, 'issue': '; '.join(token['issues'])})
            if status == 'success' and stage != 'unknown':
                sample = {'elapsedSeconds': seconds,
                          'inputTokens': None if token['issues'] else token['inputTokens'],
                          'outputTokens': None if token['issues'] else token['outputTokens'],
                          'source': source, 'sourceSHA256': digest, 'recordIndex': index}
                group['stages'].setdefault(stage, []).append(sample)
                evidence = {'source': source, 'sha256': digest}
                if evidence not in group['evidence']:
                    group['evidence'].append(evidence)
        if not synthetic_document and calls is not None and not mixed_synthetic:
            declared_calls += calls
            declared_sources += 1
            unclassified += max(0, calls - network_entries)
            if calls < network_entries:
                issues.append({'source': source, 'issue': 'declared calls are smaller than the recorded network attempts'})
        elif mixed_synthetic and not synthetic_document:
            unknown_attempt_coverage = True
            issues.append({'source': source, 'issue': 'mixed test-double entries prevent attribution of the aggregate calls counter'})
        elif not synthetic_document and calls is None:
            unknown_attempt_coverage = True
    real_network = [row for row in observations if row['status'] != 'cache-hit']
    totals = {}
    for field in ('inputTokens', 'outputTokens', 'totalTokens', 'elapsedSeconds'):
        known = [row[field] for row in real_network if row[field] is not None and not (field.endswith('Tokens') and row['issues'])]
        missing = len(real_network) - len(known) + unclassified
        totals[field] = {'knownTotal': sum(known) if known else None, 'measuredRecords': len(known),
                         'missingRecords': None if unknown_attempt_coverage else missing,
                         'complete': bool(real_network) and missing == 0 and not unknown_attempt_coverage}
    calibrations = []
    for group in identities.values():
        if group['stages']:
            calibrations.append({'kind': 'measured', 'identity': group['identity'], 'stages': group['stages'],
                                 'basis': group['evidence'],
                                 'metadataComplete': all(isinstance(v, str) and bool(v) for v in group['identity'].values())
                                     and bool(re.fullmatch(r'[0-9a-f]{64}', group['identity'].get('skillFingerprint') or ''))})
    return {
        'status': 'no-real-observations' if not real_network else ('partial' if issues or unclassified or not all(v['complete'] for v in totals.values()) else 'measured'),
        'sources': sources, 'declaredNetworkCalls': declared_calls if declared_sources and not unknown_attempt_coverage else None,
        'recordedNetworkAttempts': len(real_network), 'unclassifiedAttempts': unclassified,
        'attemptCoverageComplete': not unknown_attempt_coverage and bool(real_sources) and unclassified == 0,
        'outcomes': {'success': sum(row['status'] == 'success' for row in observations),
                     'failed': sum(row['status'] == 'failed' for row in observations),
                     'cacheHits': sum(row['status'] == 'cache-hit' for row in observations),
                     'cacheHistoryComplete': cache_complete and bool(real_sources),
                     'failureHistoryComplete': failed_complete and bool(real_sources)},
        'excludedTestDoubleRecords': excluded, 'totals': totals, 'observations': observations,
        'calibrations': calibrations,
        'calibration': calibrations[0] if len(calibrations) == 1 and calibrations[0]['metadataComplete'] else None,
        'issues': issues,
        'notes': ['Missing usage is not zero. Aggregate calls with no per-attempt record remain unclassified.',
                  'Local cache hits are not model requests; provider-side cached tokens remain part of the reported input.',
                  'Only successful real responses calibrate future successful responses. Failed attempt costs/latency remain separately reported.',
                  'Different provider/model/skill identities are never silently pooled.'],
    }


def baseline_from_files(paths):
    documents = []
    for path in paths:
        file = Path(path)
        if not file.is_file():
            raise ValueError('Expected an explicit usage log file: ' + str(file))
        raw = file.read_bytes()
        documents.append({'source': file.name, 'sha256': hashlib.sha256(raw).hexdigest(),
                          'data': json.loads(raw.decode('utf-8'))})
    return usage_baseline(documents)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    estimate = sub.add_parser('estimate')
    estimate.add_argument('scope', type=Path)
    estimate.add_argument('--calibration', type=Path)
    estimate.add_argument('--prices', type=Path)
    estimate.add_argument('--cache-hits', type=Path)
    estimate.add_argument('--completed-stage', action='append', choices=STAGES, default=[])
    estimate.add_argument('--out', type=Path, required=True)
    baseline = sub.add_parser('baseline')
    baseline.add_argument('logs', type=Path, nargs='+')
    baseline.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    load = lambda p: json.loads(p.read_text(encoding='utf-8')) if p else None
    try:
        protected = [args.scope, args.calibration, args.prices, args.cache_hits] if args.command == 'estimate' else args.logs
        if args.out.resolve() in {p.resolve() for p in protected if p is not None}:
            raise ValueError('Output must not overwrite a source or calibration log')
        if args.command == 'estimate':
            result = estimate_work(load(args.scope), load(args.calibration), load(args.prices), load(args.cache_hits), args.completed_stage)
        else:
            result = baseline_from_files(args.logs)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(json.dumps({'status': result['status'], 'out': str(args.out)}, ensure_ascii=False))
        return 0
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(json.dumps({'status': 'invalid', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
