"""Derive estimator inputs from observed extraction/plan data, not subject names."""


def scope_from_job(extraction, inventory=None, plan=None, sample_plan=None, max_model_calls=None, spent_model_calls=0):
    pages = extraction.get('pages') if isinstance(extraction, dict) else None
    if not isinstance(pages, list) or not pages or any(not isinstance(p, dict) or not isinstance(p.get('id'), str) or not p['id'] for p in pages):
        raise ValueError('extraction.pages must contain identified pages or text segments')
    page_ids = {p['id'] for p in pages}
    if len(page_ids) != len(pages):
        raise ValueError('extraction contains duplicate page IDs')
    scope = {'pageCount': len(pages)}
    if max_model_calls is not None:
        if type(max_model_calls) is not int or max_model_calls < 1:
            raise ValueError('max_model_calls must be a positive integer')
        scope['maxModelCalls'] = max_model_calls
    if type(spent_model_calls) is not int or spent_model_calls < 0:
        raise ValueError('spent_model_calls must be a nonnegative integer')
    scope['spentModelCalls'] = spent_model_calls
    if plan is not None:
        chapters = plan.get('chapters') if isinstance(plan, dict) else None
        items = inventory.get('items') if isinstance(inventory, dict) else None
        if not isinstance(chapters, list) or not chapters or not isinstance(items, list):
            raise ValueError('a plan needs nonempty chapters and the observed source inventory')
        by_item = {item.get('id'): item for item in items if isinstance(item, dict)}
        if len(by_item) != len(items) or any(not isinstance(key, str) or not key for key in by_item):
            raise ValueError('source inventory IDs are missing or duplicated')
        included, used_items, used_units, used_chapters = set(), set(), set(), set()
        for chapter in chapters:
            units = chapter.get('units') if isinstance(chapter, dict) else None
            if not isinstance(units, list) or not units:
                raise ValueError('each planned chapter needs processing units')
            if not isinstance(chapter.get('id'), str) or not chapter['id'] or chapter['id'] in used_chapters:
                raise ValueError('chapter IDs are missing or duplicated')
            used_chapters.add(chapter['id'])
            for unit in units:
                if not isinstance(unit, dict) or not isinstance(unit.get('id'), str) or not unit['id'] or unit['id'] in used_units:
                    raise ValueError('processing unit IDs are missing or duplicated')
                used_units.add(unit['id'])
                ids = unit.get('itemIds')
                if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or any(i not in by_item for i in ids):
                    raise ValueError('processing unit references an unknown or duplicated item')
                if used_items.intersection(ids):
                    raise ValueError('a source item was assigned to more than one processing unit')
                used_items.update(ids)
                actual = {by_item[i].get('pageId') for i in ids}
                if not actual <= page_ids or len(actual) > 8:
                    raise ValueError('a processing unit must use at most eight identified original pages')
                included.update(actual)
        scope.update(includedPageCount=len(included), chapterCount=len(chapters), unitCount=len(used_units))
    if sample_plan is not None:
        samples = sample_plan.get('samples') if isinstance(sample_plan, dict) else None
        if not isinstance(samples, list) or not samples or any(not isinstance(s, dict) or not isinstance(s.get('sampleId'), str) or not s['sampleId'] for s in samples):
            raise ValueError('sample plan must contain identified selected samples')
        if len({s['sampleId'] for s in samples}) != len(samples):
            raise ValueError('sample plan has duplicate sample IDs')
        scope['sampleCount'] = len(samples)
    return scope


def estimate_job(estimator, extraction, inventory=None, plan=None, sample_plan=None,
                 max_model_calls=None, calibration=None, prices=None, confirmed_cache_hits=None,
                 spent_model_calls=0, completed_stages=None):
    """The caller supplies the pinned skill's estimate_work function."""
    scope = scope_from_job(extraction, inventory, plan, sample_plan, max_model_calls, spent_model_calls)
    return estimator(scope, calibration=calibration, prices=prices, confirmed_cache_hits=confirmed_cache_hits,
                     completed_stages=completed_stages)


def _read_object(path):
    import hashlib
    import json
    from pathlib import Path
    file = Path(path)
    if file.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('估算配置文件超过 2 MiB。')
    raw = file.read_bytes()
    value = json.loads(raw.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('估算配置必须是 JSON 对象。')
    return value, hashlib.sha256(raw).hexdigest()


class JobEstimate:
    """Local advisory estimate; persisted usage is the budget authority."""
    def __init__(self, config, root, extraction, *, test_double=False):
        import importlib.util
        from pathlib import Path
        self.config, self.root, self.extraction = config, Path(root), extraction
        self.inventory = self.plan = self.sample_plan = None
        self.completed = set()
        self.phase = '资料读取后'
        self.test_double = test_double
        spec = importlib.util.spec_from_file_location('portal_work_estimator', config.skill_dir / 'scripts/estimate_work.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.calibration = self.prices = None
        self.input_evidence = {}
        for field, target in [('estimation_calibration_file', 'calibration'), ('estimation_prices_file', 'prices')]:
            configured = getattr(config, field, '')
            if configured:
                value, digest = _read_object(configured)
                setattr(self, target, value)
                self.input_evidence[target] = {'sha256': digest, 'source': 'explicit-server-configuration'}

    def update(self, *, inventory=None, plan=None, sample_plan=None, completed=(), phase=None):
        if inventory is not None:
            self.inventory = inventory
        if plan is not None:
            self.plan = plan
        if sample_plan is not None:
            self.sample_plan = sample_plan
        self.completed.update(completed)
        if phase:
            self.phase = phase
        return self.refresh()

    def refresh(self):
        import hashlib
        import json
        import time
        from .model import save_json
        from .skill_sync import skill_metadata
        usage_path = self.root / 'model-usage.json'
        baseline = None
        calls = 0
        if usage_path.is_file():
            raw = usage_path.read_bytes()
            ledger = json.loads(raw.decode('utf-8'))
            if type(ledger.get('calls')) is not int or ledger['calls'] < 0:
                raise ValueError('调用日志的限额计数无效。')
            calls = ledger['calls']
            if self.test_double:
                ledger = {**ledger, 'testDouble': True}
            baseline = self.module.usage_baseline([{'source': 'model-usage.json',
                'sha256': hashlib.sha256(raw).hexdigest(), 'data': ledger}])
        scope = scope_from_job(self.extraction, self.inventory, self.plan, self.sample_plan,
                               self.config.max_model_calls, spent_model_calls=calls)
        identity = {'provider': self.config.provider, 'model': self.config.model,
                    'skillFingerprint': skill_metadata(self.config.skill_dir)['fingerprint']}
        calibration = self.calibration
        if calibration is not None and calibration.get('kind') == 'measured' and calibration.get('identity') != identity:
            raise ValueError('实测估算基线与当前服务商、模型或组件版本不一致。')
        if calibration is None and baseline and not self.test_double:
            calibration = next((c for c in baseline['calibrations']
                                if c['metadataComplete'] and c['identity'] == identity), None)
        report = self.module.estimate_work(scope, calibration=calibration, prices=self.prices,
                                           completed_stages=sorted(self.completed))
        report.update(formatVersion=1, phase=self.phase, updatedAt=time.time(), testDouble=self.test_double,
                      explicitInputs=self.input_evidence, priceSupplied=self.prices is not None,
                      usage=baseline)
        save_json(self.root / 'work-estimate.json', report)
        return report


def public_estimate(path):
    """Expose only counters and ranges, never input paths, prompts or ledger rows."""
    import json
    import math
    from pathlib import Path
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        return None
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        if raw.get('formatVersion') != 1:
            return None
        def number(value):
            if type(value) not in (int, float):
                return None
            try:
                return value if math.isfinite(value) and value >= 0 else None
            except OverflowError:
                return None
        text = lambda v, limit=200: v[:limit] if isinstance(v, str) else ''
        def interval(value):
            value = value if isinstance(value, dict) else {}
            return {'low': number(value.get('low')), 'high': number(value.get('high')),
                    'status': value.get('status') if value.get('status') in ('unknown', 'conditional') else None}
        calls = raw.get('calls', {})
        metrics = raw.get('successfulResponseEstimates', {})
        usage = raw.get('usage') or {}
        outcomes = usage.get('outcomes', {})
        totals = usage.get('totals', {})
        result = {'phase': text(raw.get('phase')), 'updatedAt': number(raw.get('updatedAt')),
            'testDouble': raw.get('testDouble') is True,
            'scope': {key: number(raw.get('scope', {}).get(key)) for key in
                      ('pageCount', 'includedPageCount', 'chapterCount', 'unitCount', 'sampleCount')},
            'calls': {key: number(calls.get(key)) for key in ('maxModelCalls', 'spentModelCalls', 'availableModelCalls')},
            'completedStages': [x for x in raw.get('completedStages', []) if x in
                ('inventory', 'plan', 'generation', 'review', 'global-review', 'independent-source', 'independent-compare', 'visual-review')],
            'calibrated': raw.get('calibration', {}).get('status') == 'conditional',
            'metrics': {key: interval(metrics.get(key)) for key in ('inputTokens', 'outputTokens', 'elapsedSeconds')},
            'usage': {'outcomes': {key: number(outcomes.get(key)) for key in ('success', 'failed', 'cacheHits')},
                      'unclassifiedAttempts': number(usage.get('unclassifiedAttempts')),
                      'totals': {key: {'knownTotal': number(totals.get(key, {}).get('knownTotal')),
                          'complete': totals.get(key, {}).get('complete') is True}
                          for key in ('inputTokens', 'outputTokens', 'totalTokens', 'elapsedSeconds')}}}
        result['calls'].update(successfulResponses=interval(calls.get('successfulResponses')),
                               networkAttempts=interval(calls.get('networkAttempts')),
                               limitAssessment=calls.get('limitAssessment') if calls.get('limitAssessment') in
                                ('unknown', 'below-minimum', 'may-stop-before-worst-case', 'covers-count-bound') else 'unknown')
        cost = metrics.get('cost') or {}
        result['metrics']['cost'] = interval(cost) if raw.get('priceSupplied') is True else interval({})
        result['metrics']['cost']['currency'] = text(cost.get('currency'), 16) if raw.get('priceSupplied') is True else None
        result['priceSupplied'] = raw.get('priceSupplied') is True
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        return None
