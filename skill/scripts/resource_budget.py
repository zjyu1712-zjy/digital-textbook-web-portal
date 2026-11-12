"""Measure the actual self-contained HTML; all byte buckets are disjoint."""
import base64
import binascii
import hashlib
import json
import re


MIB = 1024 * 1024
DEFAULT_WARNING_BYTES = 60 * MIB
DEFAULT_LIMIT_BYTES = 100 * MIB
_URI = re.compile(rb'data:(image/[A-Za-z0-9.+-]+|font/[A-Za-z0-9.+-]+|application/(?:font-woff|vnd\.ms-fontobject));base64,([^\s\"\'<>)]*)')
_SCRIPT = re.compile(rb'<script\b([^>]*)>(.*?)</script\s*>', re.I | re.S)
_STYLE = re.compile(rb'<style\b[^>]*>(.*?)</style\s*>', re.I | re.S)
_COURSE_ID = re.compile(rb'(?<![-:\w])id\s*=\s*[\"\']course-data[\"\']', re.I)


class ResourceBudgetExceeded(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__('HTML体积超过配置上限：%d bytes > %d bytes；请先查看资源报告，优化图片或明确缩小本次交付范围。' %
                         (report['totalBytes'], report['policy']['limitBytes']))


def validate_thresholds(warning_bytes, limit_bytes):
    if (type(warning_bytes) is not int or type(limit_bytes) is not int or
            warning_bytes <= 0 or limit_bytes <= warning_bytes):
        raise ValueError('资源阈值必须为正整数字节数，且提醒阈值小于阻断阈值。')
    return {'warningBytes': warning_bytes, 'limitBytes': limit_bytes}


def _image_metadata(course):
    found = {}
    def visit(value):
        if isinstance(value, dict):
            if value.get('type') == 'image' and isinstance(value.get('data'), str):
                found.setdefault(value['data'], []).append({
                    'path': value.get('path'), 'declaredSHA256': value.get('sha256')})
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
    visit(course)
    return found


def analyze_html(html, warning_bytes=DEFAULT_WARNING_BYTES, limit_bytes=DEFAULT_LIMIT_BYTES):
    """Accept final HTML text/UTF-8 bytes, without reading assets or writing files.

    Resource URI prefixes and base64 characters belong to their resource bucket.
    JSON quotes, CSS declarations and HTML tags stay in their respective buckets.
    The same URI repeated in different places costs bytes every time.
    """
    policy = validate_thresholds(warning_bytes, limit_bytes)
    if isinstance(html, str):
        raw = html.encode('utf-8')
    elif isinstance(html, bytes):
        raw = html
        raw.decode('utf-8')
    else:
        raise TypeError('html must be text or UTF-8 bytes')
    regions = []
    course = None
    seen_course = False
    for match in _SCRIPT.finditer(raw):
        kind = 'courseData' if _COURSE_ID.search(match.group(1)) else 'scripts'
        regions.append((match.start(2), match.end(2), kind))
        if kind == 'courseData':
            if seen_course:
                raise ValueError('只能分析包含一个course-data的教材HTML。')
            seen_course = True
            try:
                course = json.loads(match.group(2).decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as error:
                raise ValueError('course-data不是有效UTF-8 JSON，无法可靠归属图片。') from error
    regions += [(match.start(1), match.end(1), 'styles') for match in _STYLE.finditer(raw)]
    regions.sort()
    if any(a[1] > b[0] for a, b in zip(regions, regions[1:])):
        raise ValueError('脚本与样式范围重叠，无法可靠计算分项。')
    metadata = _image_metadata(course)
    used = {}
    parts = {name: 0 for name in ['images', 'fonts', 'scripts', 'courseData', 'styles', 'other']}
    for start, end, kind in regions:
        parts[kind] += end - start
    parts['other'] = len(raw) - sum(parts.values())
    resources = {'images': [], 'fonts': []}
    for match in _URI.finditer(raw):
        uri = match.group(0).decode('ascii')
        try:
            decoded = base64.b64decode(match.group(2), validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError('内嵌资源不是有效base64，不能生成通过的资源报告。') from error
        kind = 'images' if match.group(1).startswith(b'image/') else 'fonts'
        size = match.end() - match.start()
        container = 'other'
        for start, end, name in regions:
            if start <= match.start() and match.end() <= end:
                container = name
                break
        parts[container] -= size
        parts[kind] += size
        row = {'mime': match.group(1).decode('ascii'), 'rawBytes': len(decoded),
               'embeddedBytes': size, 'sha256': hashlib.sha256(decoded).hexdigest()}
        if kind == 'images':
            index = used.get(uri, 0)
            candidates = metadata.get(uri, []) if container == 'courseData' else []
            row.update(candidates[index] if index < len(candidates) else {'path': None, 'declaredSHA256': None})
            if container == 'courseData':
                used[uri] = index + 1
        resources[kind].append(row)
    assert all(value >= 0 for value in parts.values()) and sum(parts.values()) == len(raw)
    grouped = {}
    for item in resources['images']:
        key = (item['path'], item['sha256'])
        if key not in grouped:
            grouped[key] = {**item, 'occurrences': 0, 'embeddedBytes': 0}
        grouped[key]['occurrences'] += 1
        grouped[key]['embeddedBytes'] += item['embeddedBytes']
    images = sorted(grouped.values(), key=lambda item: (-item['embeddedBytes'], str(item['path'])))
    warnings = []
    if len(raw) > policy['warningBytes']:
        warnings.append('HTML超过提醒阈值；先检查最大图片及重复内嵌开销，并在目标设备实测。')
    if any(item['rawBytes'] > 2 * MIB for item in images):
        warnings.append('存在大于2MiB的单张原图片；优化前后核对小字、公式、图例和颜色含义。')
    if len(resources['images']) > len({item['sha256'] for item in resources['images']}):
        warnings.append('同一图片在多处重复内嵌，报告已按每次出现计入体积。')
    if any(item['declaredSHA256'] and item['declaredSHA256'] != item['sha256'] for item in resources['images']):
        warnings.append('发现图片声明摘要与内嵌字节不同；需检查来源和当前图片绑定。')
    status = 'blocked' if len(raw) > policy['limitBytes'] else ('warning' if len(raw) > policy['warningBytes'] else 'ok')
    return {
        'version': 1, 'status': status, 'totalBytes': len(raw),
        'htmlSHA256': hashlib.sha256(raw).hexdigest(), 'policy': policy, 'parts': parts,
        'images': {'occurrences': len(resources['images']), 'uniqueContentCount': len({x['sha256'] for x in resources['images']}),
                   'rawBytesWithRepetitions': sum(x['rawBytes'] for x in resources['images']),
                   'embeddedBytes': parts['images'], 'items': images, 'largestFive': images[:5]},
        'fonts': {'occurrences': len(resources['fonts']), 'rawBytesWithRepetitions': sum(x['rawBytes'] for x in resources['fonts']),
                  'embeddedBytes': parts['fonts'], 'uniqueContentCount': len({x['sha256'] for x in resources['fonts']})},
        'warnings': warnings,
        'note': 'parts按最终UTF-8字节互斥计数，总和等于totalBytes；图片与字体包含data URI前缀。体积通过不代表页面流畅或内容正确。',
        'nextSteps': ['使用显式图片优化工具生成副本，并实际查看可读性后更新引用与审校。',
                      '按明确的章节范围分批制作，每份仍自包含；范围和未交付章节须明示。',
                      '确有设备实测依据时调整阈值；本工具不会静默外置图片或建立跨文件共享存储承诺。'],
    }


def enforce_budget(report):
    """Enforce the measured byte budget, independent of content completeness."""
    policy = validate_thresholds(report['policy']['warningBytes'], report['policy']['limitBytes'])
    if type(report.get('totalBytes')) is not int or report['totalBytes'] < 0:
        raise ValueError('资源报告缺少有效totalBytes。')
    if report['totalBytes'] > policy['limitBytes']:
        raise ResourceBudgetExceeded(report)
    return report
