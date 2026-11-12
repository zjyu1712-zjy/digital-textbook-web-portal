"""Originals, colour/alpha/animation and explicit output boundaries survive."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from optimize_images import optimize_images
try:
    from PIL import Image
except ImportError:
    Image = None


class OptimizerValidationTests(unittest.TestCase):
    def test_invalid_configuration_does_not_need_pillow(self):
        for kwargs in [{'profile': 'bad'}, {'max_edge': True}, {'max_edge': 0}, {'quality': 0},
                       {'profile': 'diagram', 'quality': 90}, {'grayscale': True}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                optimize_images([], '/unwritten/output', **kwargs)


@unittest.skipIf(Image is None, 'Pillow is optional; run image tests in a Pillow environment')
class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make(self, name, mode='RGB', size=(80, 60), colour=(10, 90, 200)):
        path = self.root / name
        Image.new(mode, size, colour).save(path)
        return path

    def test_diagram_preserves_pixels_and_original_and_records_hashes(self):
        path = self.make('图.png')
        original = path.read_bytes()
        report = optimize_images([path], self.root / 'out')
        result = self.root / 'out' / report['items'][0]['output']['path']
        self.assertEqual(path.read_bytes(), original)
        with Image.open(path) as before, Image.open(result) as after:
            self.assertEqual(after.size, before.size)
            self.assertEqual(after.convert('RGBA').tobytes(), before.convert('RGBA').tobytes())
        item = report['items'][0]
        self.assertEqual(item['source']['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(item['output']['sha256'], hashlib.sha256(result.read_bytes()).hexdigest())
        self.assertEqual(item['reviewStatus'], 'required')
        self.assertEqual(json.loads((self.root / 'out/optimization-manifest.json').read_text()), report)

    def test_photo_resizes_only_downward_and_preserves_source(self):
        path = self.make('large.png', size=(2400, 1200))
        original = path.read_bytes()
        report = optimize_images([path], self.root / 'out', profile='photo', max_edge=600)
        self.assertEqual(report['items'][0]['output']['dimensions'], [600, 300])
        self.assertIn('resized', report['items'][0]['changes'])
        self.assertEqual(path.read_bytes(), original)
        smaller = self.make('small.png', size=(64, 64))
        r = optimize_images([smaller], self.root / 'small-out', profile='photo', max_edge=600)
        self.assertEqual(r['items'][0]['output']['dimensions'], [64, 64])

    def test_transparency_does_not_get_flattened_by_photo_profile(self):
        path = self.make('alpha.png', 'RGBA', colour=(30, 50, 90, 80))
        report = optimize_images([path], self.root / 'out', profile='photo')
        with Image.open(self.root / 'out' / report['items'][0]['output']['path']) as output:
            self.assertEqual(output.convert('RGBA').getpixel((0, 0)), (30, 50, 90, 80))

    def test_scan_keeps_colours_unless_grayscale_requested(self):
        path = self.make('scan.png', size=(1000, 500), colour=(255, 0, 0))
        report = optimize_images([path], self.root / 'colour', profile='scan', max_edge=500)
        with Image.open(self.root / 'colour' / report['items'][0]['output']['path']) as output:
            self.assertEqual(output.mode, 'RGB')
        report = optimize_images([path], self.root / 'gray', profile='scan', grayscale=True)
        with Image.open(self.root / 'gray' / report['items'][0]['output']['path']) as output:
            self.assertEqual(output.mode, 'L')

    def test_animated_gif_remains_byte_identical(self):
        path = self.root / 'animated.gif'
        first = Image.new('RGB', (80, 60), 'red')
        first.save(path, save_all=True, append_images=[Image.new('RGB', (80, 60), 'blue')], duration=[70, 100], loop=2)
        report = optimize_images([path], self.root / 'out', profile='photo', max_edge=64)
        result = self.root / 'out' / report['items'][0]['output']['path']
        self.assertEqual(result.read_bytes(), path.read_bytes())
        self.assertEqual(report['items'][0]['output']['frames'], 2)
        self.assertEqual(report['items'][0]['changes'], ['animated-original-preserved'])

    def test_cmyk_is_not_silently_converted_to_rgb(self):
        path = self.make('cmyk.jpg', mode='CMYK', colour=(0, 30, 60, 0))
        report = optimize_images([path], self.root / 'out', profile='photo')
        result = self.root / 'out' / report['items'][0]['output']['path']
        self.assertEqual(result.read_bytes(), path.read_bytes())
        self.assertEqual(report['items'][0]['changes'], ['special-colour-mode-original-preserved'])

    def test_existing_output_and_duplicate_input_are_rejected(self):
        path = self.make('source.png')
        out = self.root / 'existing'
        out.mkdir()
        sentinel = out / 'do-not-touch.txt'
        sentinel.write_text('keep')
        with self.assertRaises(ValueError):
            optimize_images([path], out)
        self.assertEqual(sentinel.read_text(), 'keep')
        with self.assertRaises(ValueError):
            optimize_images([path, path], self.root / 'duplicate')
        self.assertFalse((self.root / 'duplicate').exists())

    def test_invalid_later_image_leaves_no_partial_output(self):
        valid = self.make('valid.png')
        broken = self.root / 'broken.png'
        broken.write_bytes(b'not an image')
        with self.assertRaises(OSError):
            optimize_images([valid, broken], self.root / 'out')
        self.assertFalse((self.root / 'out').exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['broken.png', 'valid.png'])

    def test_source_changed_during_operation_is_not_published(self):
        path = self.make('source.png')
        from optimize_images import _sha
        count = 0
        def changed(file):
            nonlocal count
            if file.resolve() == path.resolve():
                count += 1
                if count >= 2:
                    return '0' * 64
            return _sha(file)
        with patch('optimize_images._sha', side_effect=changed), self.assertRaises(ValueError):
            optimize_images([path], self.root / 'out')
        self.assertFalse((self.root / 'out').exists())
        self.assertEqual([p.name for p in self.root.iterdir()], ['source.png'])


if __name__ == '__main__':
    unittest.main()
