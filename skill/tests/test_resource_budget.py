"""Budget decisions and actual UTF-8 accounting, without a browser or Pillow."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from resource_budget import analyze_html, enforce_budget, ResourceBudgetExceeded


def uri(kind, data):
    return 'data:' + kind + ';base64,' + base64.b64encode(data).decode()


def html(course, css='', js=''):
    payload = json.dumps(course, ensure_ascii=False, separators=(',', ':'))
    return '<!doctype html><title>测试教材</title><style>' + css + '</style><script id="course-data" type="application/json">' + payload + '</script><script>' + js + '</script>', payload


class ResourceBudgetTests(unittest.TestCase):
    def test_disjoint_exact_utf8_breakdown_and_repeated_images(self):
        image = uri('image/png', b'12345')
        font = uri('font/woff2', b'abcdef')
        source = {'type': 'image', 'path': '图.png', 'data': image, 'sha256': hashlib.sha256(b'12345').hexdigest()}
        css = '@font-face{src:url(' + font + ')}'
        js = 'const 标题="课本";'
        document, payload = html({'blocks': [source, source]}, css, js)
        r = analyze_html(document)
        self.assertEqual(r['totalBytes'], len(document.encode('utf-8')))
        self.assertEqual(r['parts']['images'], len(image) * 2)
        self.assertEqual(r['parts']['fonts'], len(font))
        self.assertEqual(r['parts']['scripts'], len(js.encode('utf-8')))
        self.assertEqual(r['parts']['courseData'], len(payload.encode('utf-8')) - len(image) * 2)
        self.assertEqual(r['parts']['styles'], len(css) - len(font))
        self.assertEqual(sum(r['parts'].values()), r['totalBytes'])
        self.assertEqual(r['images']['rawBytesWithRepetitions'], 10)
        self.assertEqual(r['images']['uniqueContentCount'], 1)
        self.assertEqual(r['images']['largestFive'][0]['path'], '图.png')
        self.assertEqual(r['images']['largestFive'][0]['occurrences'], 2)
        self.assertEqual(r['images']['largestFive'][0]['sha256'], source['sha256'])
        self.assertTrue(r['warnings'])

    def test_threshold_boundaries_and_exception_retains_report(self):
        self.assertEqual(analyze_html('a' * 10, 10, 20)['status'], 'ok')
        self.assertEqual(analyze_html('a' * 11, 10, 20)['status'], 'warning')
        self.assertEqual(analyze_html('a' * 20, 10, 20)['status'], 'warning')
        report = analyze_html('a' * 21, 10, 20)
        self.assertEqual(report['status'], 'blocked')
        with self.assertRaises(ResourceBudgetExceeded) as caught:
            enforce_budget(report)
        self.assertIs(caught.exception.report, report)
        report['status'] = 'ok'
        with self.assertRaises(ResourceBudgetExceeded):
            enforce_budget(report)

    def test_invalid_thresholds_are_rejected(self):
        for warning, limit in [(True, 5), (1, False), (1.0, 5), (-1, 5), (0, 5), (5, 5), (6, 5), (1, float('inf'))]:
            with self.subTest(warning=warning, limit=limit), self.assertRaises(ValueError):
                analyze_html('', warning, limit)

    def test_largest_five_include_repetition_cost(self):
        small = {'type': 'image', 'path': 'reused.png', 'data': uri('image/png', b'x')}
        course = {'blocks': [small] * 10 + [{'type': 'image', 'path': str(n) + '.png', 'data': uri('image/png', bytes(n))} for n in range(10, 16)]}
        r = analyze_html(html(course)[0])
        self.assertEqual(len(r['images']['largestFive']), 5)
        self.assertEqual(r['images']['largestFive'][0]['path'], 'reused.png')
        self.assertEqual(r['images']['occurrences'], 16)

    def test_attribute_image_does_not_consume_course_path_metadata(self):
        image = uri('image/png', b'abc')
        document = '<img src="' + image + '">' + html({'image': {'type': 'image', 'path': 'named.png', 'data': image}})[0]
        r = analyze_html(document)
        self.assertEqual({x['path'] for x in r['images']['items']}, {None, 'named.png'})
        self.assertEqual(r['images']['uniqueContentCount'], 1)
        self.assertTrue(r['warnings'])

    def test_invalid_encoded_bytes_do_not_get_a_valid_report(self):
        for bad in ['data:image/png;base64,abc', 'data:image/png;base64,YWJj!']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                analyze_html('<img src="' + bad + '">')
        with self.assertRaises(UnicodeDecodeError):
            analyze_html(b'\xff')

    def test_malformed_or_ambiguous_course_data_rejected(self):
        with self.assertRaises(ValueError):
            analyze_html('<script id="course-data">{bad}</script>')
        with self.assertRaises(ValueError):
            analyze_html('<script id="course-data">{}</script>' * 2)
        with self.assertRaises(ValueError):
            analyze_html('<script id="course-data">null</script><script id="course-data">{}</script>')

    def test_data_attribute_is_not_the_course_data_element(self):
        r = analyze_html('<script data-id="course-data">window.valid=true;</script>')
        self.assertEqual(r['parts']['courseData'], 0)
        self.assertEqual(r['parts']['scripts'], len('window.valid=true;'))

    def test_raw_bytes_and_text_produce_the_same_report(self):
        document = html({'title': '有中文的教材'})[0]
        self.assertEqual(analyze_html(document), analyze_html(document.encode('utf-8')))

    def test_changed_image_digest_is_visible(self):
        document = html({'block': {'type': 'image', 'path': 'x.png', 'sha256': '0' * 64, 'data': uri('image/png', b'actual')}})[0]
        self.assertTrue(any('声明摘要' in x for x in analyze_html(document)['warnings']))

    def test_optional_dependency_not_required_for_empty_image_course(self):
        r = analyze_html(html({'title': 'Text only'}, js='window.ok=true;')[0])
        self.assertEqual(r['images']['occurrences'], 0)
        self.assertEqual(r['fonts']['occurrences'], 0)
        self.assertEqual(sum(r['parts'].values()), r['totalBytes'])


if __name__ == '__main__':
    unittest.main()
