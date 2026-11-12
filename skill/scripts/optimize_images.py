"""Explicit image-copy preparation; originals and course JSON are never changed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


PROFILES = {'diagram': {'maxEdge': None, 'quality': None},
            'scan': {'maxEdge': 2000, 'quality': 88},
            'photo': {'maxEdge': 1600, 'quality': 85}}
SUPPORTED = {'PNG', 'JPEG', 'WEBP', 'GIF'}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError as error:
        raise ValueError('图片优化需要可选依赖Pillow；原图、普通构建和资源报告均不依赖它。请使用宿主已有的Pillow环境。') from error
    return Image, ImageOps


def optimize_images(paths, output_dir, profile='diagram', max_edge=None, quality=None, grayscale=False):
    """Write images and manifest to a new directory, failing before input changes.

    diagram defaults to preserving pixel dimensions and lossless PNG. Explicit
    resizing and scan/photo JPEG may lose fine detail: output stays review-required.
    Animated input is copied byte-for-byte; transparency uses lossless PNG.
    """
    if profile not in PROFILES:
        raise ValueError('profile必须是diagram、scan或photo。')
    if max_edge is not None and (type(max_edge) is not int or not 64 <= max_edge <= 20000):
        raise ValueError('max_edge须为64至20000的整数，未指定时使用预设。')
    if quality is not None and (type(quality) is not int or not 1 <= quality <= 100):
        raise ValueError('quality须为1至100的整数。')
    if profile == 'diagram' and quality is not None:
        raise ValueError('diagram使用无损编码，不接受JPEG质量参数。')
    if type(grayscale) is not bool:
        raise ValueError('grayscale须为布尔值。')
    if grayscale and profile != 'scan':
        raise ValueError('灰度转换只接受显式scan配置；不可默认删除图表颜色含义。')
    input_paths = [Path(path).expanduser().resolve() for path in paths]
    if not input_paths or len(input_paths) != len(set(input_paths)):
        raise ValueError('提供至少一张明确图片路径，且不能重复。')
    output = Path(output_dir).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('输出目录必须不存在；不会覆盖既有文件或目录。')
    if not output.parent.is_dir():
        raise ValueError('输出目录的父目录必须已经存在。')
    for path in input_paths:
        if not path.is_file():
            raise ValueError('图片不存在或不是普通文件：' + str(path))
    Image, ImageOps = _pillow()
    edge = max_edge if max_edge is not None else PROFILES[profile]['maxEdge']
    jpeg_quality = quality if quality is not None else PROFILES[profile]['quality']
    plan = []
    for path in input_paths:
        with Image.open(path) as original:
            if original.format not in SUPPORTED:
                raise ValueError('仅接受PNG、JPEG、WebP和GIF栅格图：' + path.name)
            original.verify()
        with Image.open(path) as original:
            plan.append({'path': path, 'sha256': _sha(path), 'bytes': path.stat().st_size,
                         'format': original.format, 'mode': original.mode, 'dimensions': list(original.size),
                         'frames': getattr(original, 'n_frames', 1)})
    staging = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=str(output.parent)))
    try:
        items = []
        for index, item in enumerate(plan, 1):
            source = item['path']
            if _sha(source) != item['sha256']:
                raise ValueError('图片在准备过程中发生变化：' + source.name)
            prefix = '%03d-%s' % (index, item['sha256'][:12])
            changes = []
            preserve_colour = item['mode'] not in ('1', 'L', 'LA', 'P', 'RGB', 'RGBA')
            if item['frames'] > 1 or preserve_colour:
                suffix = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp', 'GIF': '.gif'}[item['format']]
                dest = staging / (prefix + suffix)
                shutil.copyfile(source, dest)
                changes.append('animated-original-preserved' if item['frames'] > 1 else 'special-colour-mode-original-preserved')
            else:
                with Image.open(source) as original:
                    original.load()
                    image = ImageOps.exif_transpose(original)
                    if image.size != original.size or original.getexif().get(274, 1) != 1:
                        changes.append('orientation-normalized')
                    transparent = 'A' in image.getbands() or 'transparency' in image.info
                    if edge and max(image.size) > edge:
                        resampling = getattr(Image, 'Resampling', Image)
                        image.thumbnail((edge, edge), resampling.LANCZOS)
                        changes.append('resized')
                    if grayscale:
                        image = image.convert('LA' if transparent else 'L')
                        changes.append('explicit-grayscale')
                    if transparent or profile == 'diagram':
                        if transparent:
                            image = image.convert('LA' if grayscale else 'RGBA')
                        elif image.mode not in ('1', 'L', 'LA', 'P', 'RGB', 'RGBA', 'I', 'I;16'):
                            image = image.convert('RGB')
                        dest = staging / (prefix + '.png')
                        image.save(dest, 'PNG', optimize=True, icc_profile=image.info.get('icc_profile'))
                        changes.append('lossless-png')
                        if transparent:
                            changes.append('transparency-preserved')
                    else:
                        image = image.convert('L' if grayscale else 'RGB')
                        dest = staging / (prefix + '.jpg')
                        image.save(dest, 'JPEG', quality=jpeg_quality, optimize=True,
                                   icc_profile=image.info.get('icc_profile'))
                        changes.append('jpeg-reencoded')
                # Do not increase size or introduce unnecessary re-encoding when
                # the caller did not request a geometric/colour transformation.
                if dest.stat().st_size >= item['bytes'] and not any(x in changes for x in ['resized', 'explicit-grayscale', 'orientation-normalized']):
                    dest.unlink()
                    suffix = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp', 'GIF': '.gif'}[item['format']]
                    dest = staging / (prefix + suffix)
                    shutil.copyfile(source, dest)
                    changes = ['smaller-original-preserved']
            with Image.open(dest) as final:
                final.load()
                dimensions = list(final.size)
                frames = getattr(final, 'n_frames', 1)
                fmt = final.format
                mode = final.mode
            if item['frames'] > 1 and (frames != item['frames'] or _sha(dest) != item['sha256']):
                raise ValueError('动画原件复制验证失败。')
            if _sha(source) != item['sha256']:
                raise ValueError('源图片已改变，不发布可能过期的优化副本。')
            items.append({'source': {'path': str(source), 'sha256': item['sha256'], 'bytes': item['bytes'],
                                     'dimensions': item['dimensions'], 'format': item['format'], 'mode': item['mode'], 'frames': item['frames']},
                          'output': {'path': dest.name, 'sha256': _sha(dest), 'bytes': dest.stat().st_size,
                                     'dimensions': dimensions, 'format': fmt, 'mode': mode, 'frames': frames},
                          'changes': changes, 'reviewStatus': 'required'})
        report = {'version': 1, 'status': 'prepared-needs-review', 'profile': profile,
                  'settings': {'maxEdge': edge, 'jpegQuality': jpeg_quality, 'grayscale': grayscale},
                  'sourceBytes': sum(x['source']['bytes'] for x in items),
                  'outputBytes': sum(x['output']['bytes'] for x in items), 'items': items,
                  'note': '原图和课程JSON均未修改。先对照查看小字、公式、图例及颜色含义，再手动更新图片path/sha256并重新审校；来源文件身份摘要保持原始资料含义。动画保持原字节，不保证缩小。'}
        (staging / 'optimization-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Reserve the destination rather than replacing even an empty directory
        # created concurrently. Only this process's reserved directory is touched.
        output.mkdir(exist_ok=False)
        try:
            for file in staging.iterdir():
                os.rename(str(file), str(output / file.name))
        except Exception:
            shutil.rmtree(output)
            raise
        return report
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+', help='明确授权的源图片文件')
    parser.add_argument('--out-dir', required=True, help='不存在的输出目录，其父目录须存在')
    parser.add_argument('--profile', choices=sorted(PROFILES), default='diagram')
    parser.add_argument('--max-edge', type=int)
    parser.add_argument('--quality', type=int)
    parser.add_argument('--grayscale', action='store_true', help='仅scan可显式启用；会丢失颜色信息')
    args = parser.parse_args()
    try:
        report = optimize_images(args.images, args.out_dir, args.profile, args.max_edge, args.quality, args.grayscale)
        print(json.dumps({'status': report['status'], 'images': len(report['items']), 'sourceBytes': report['sourceBytes'],
                          'outputBytes': report['outputBytes'], 'manifest': str(Path(args.out_dir) / 'optimization-manifest.json')}, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
