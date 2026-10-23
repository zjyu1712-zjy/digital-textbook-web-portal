"""Read uploaded documents as data. Never follow document links or execute macros."""
from pathlib import Path
import hashlib
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET


class InputProblem(ValueError):
    pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _office(path, kind):
    # Office is accepted only where a lossless text/table extraction is possible.
    # Charts, equations, images and drawing layouts require the original PDF export.
    with zipfile.ZipFile(path) as z:
        members = z.infolist()
        if len(members) > 10000 or sum(m.file_size for m in members) > 100_000_000:
            raise InputProblem("文档解压后过大，请将所需范围导出为 PDF。")
        if any(m.flag_bits & 1 for m in members):
            raise InputProblem("文档已加密，请提供可以正常打开的副本。")
        names = z.namelist()
        if any(re.search(r'(?:footnotes|endnotes|header\d*|footer\d*|notesSlides/.+)\.xml$', n) for n in names):
            raise InputProblem('文档含页眉、页脚、脚注或演讲备注，请导出包含这些内容的 PDF 后上传。')
        if any('/media/' in n or '/charts/' in n or 'vbaProject' in n for n in names):
            raise InputProblem("Office 文档含图片、图表或宏；请在原应用中导出 PDF 后上传，以保留原图和布局。")
        if kind == '.docx':
            selected = ['word/document.xml']
        else:
            # slideN.xml file numbers are creation order, NOT presentation order.
            presentation = ET.fromstring(z.read('ppt/presentation.xml'))
            relationships = ET.fromstring(z.read('ppt/_rels/presentation.xml.rels'))
            targets = {r.get('Id'): r for r in relationships}
            selected = []
            for slide_id in presentation.iter():
                if slide_id.tag.rsplit('}',1)[-1] != 'sldId':
                    continue
                rid = slide_id.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                relationship = targets.get(rid)
                if relationship is None or relationship.get('TargetMode') == 'External':
                    raise InputProblem('课件页序关系缺失或含外部内容，请导出 PDF 后上传。')
                target = relationship.get('Target','')
                name = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'ppt/'+target)
                if not re.fullmatch(r'ppt/slides/slide\d+\.xml', name) or name not in names or name in selected:
                    raise InputProblem('课件页序无法确认，请导出 PDF 后上传。')
                selected.append(name)
            if not selected:
                raise InputProblem('课件没有可确认的实际页序，请导出 PDF 后上传。')
        out = []
        for index, name in enumerate(selected, 1):
            root = ET.fromstring(z.read(name))
            local = lambda tag: tag.rsplit('}', 1)[-1]
            forbidden = {'oMath', 'oMathPara', 'drawing', 'pict', 'AlternateContent', 'instrText', 'sym',
                         'graphicFrame', 'cxnSp', 'custGeom'}
            if any(local(e.tag) in forbidden for e in root.iter()):
                raise InputProblem("文档含公式、绘图或复杂布局；请导出 PDF 后上传，避免漏掉教学内容。")
            if kind == '.pptx':
                for p in root.iter():
                    if local(p.tag) == 'prstGeom' and p.get('prst') not in ('rect',):
                        raise InputProblem("课件含图形，请导出 PDF 后上传以核对图文关系。")
            lines = []
            for p in root.iter():
                if local(p.tag) in ('p', 'tr'):
                    text = ' '.join(e.text or '' for e in p.iter() if local(e.tag) == 't')
                    if text.strip():
                        lines.append(text)
            # Text tables cannot retain all merged cells, reject instead of flattening.
            if any(local(e.tag) == 'tbl' for e in root.iter()):
                raise InputProblem("文档含表格；请导出 PDF 后上传以保留单元格和数据关系。")
            out.append(('PPT 幻灯片 ' + str(index) if kind == '.pptx' else 'Word 正文段落', '\n'.join(lines)))
        return out


def extract_sources(job_dir, manifest, max_pages=800, cancelled=lambda: False):
    root = Path(job_dir).resolve()
    assets = root / 'assets'
    assets.mkdir(exist_ok=True)
    sources, pages = [], []

    def add(sid, locator, text, image=None):
        if cancelled():
            raise InputProblem('任务已取消。')
        if len(pages) >= max_pages:
            raise InputProblem(f'资料超过本站 {max_pages} 页/文字段的处理限额；请明确缩小范围后重试。未截断原文。')
        number = sum(p['sourceId'] == sid for p in pages) + 1
        pages.append({'id': f'{sid}.p{number:04}', 'sourceId': sid, 'locator': locator,
                      'text': text, 'image': image})

    for file in manifest['files']:
        path = (root / file['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise InputProblem('上传资料位置无效。')
        if digest(path) != file['sha256']:
            raise InputProblem('上传资料校验值变化，请重新提交原文件。')
        sid = file['id']
        sources.append({'id': sid, 'title': file['name'], 'role': file['role'],
                        'identity': '用户上传原件；版本以正文与封面为准', 'sha256': file['sha256'],
                        'locator': '见逐项来源定位', 'primary': file.get('primary', False)})
        ext = Path(file['name']).suffix.lower()
        if ext == '.pdf':
            try:
                import pypdfium2 as pdfium
                from pypdf import PdfReader
            except ImportError as exc:
                raise InputProblem('服务器缺少 PDF 读取组件，请联系管理者完成部署。') from exc
            try:
                reader = PdfReader(path)
                if reader.is_encrypted:
                    raise InputProblem('PDF 已加密，请提供已解锁的阅读副本。')
                doc = pdfium.PdfDocument(path)
                try:
                    if len(pages) + len(doc) > max_pages:
                        raise InputProblem(f'资料超过本站 {max_pages} 页限额；请按实际范围分批转换，未自动截断。')
                    for index in range(len(doc)):
                        if cancelled():
                            raise InputProblem('任务已取消。')
                        page = doc[index]
                        bitmap = page.render(scale=min(2, 1800/max(page.get_size())))
                        image = bitmap.to_pil().convert('RGB')
                        rel = f'assets/{sid}-p{index+1:04}.jpg'
                        image.save(root / rel, 'JPEG', quality=88)
                        text = reader.pages[index].extract_text() or ''
                        add(sid, f'PDF 物理页 {index+1}', text, rel)
                        bitmap.close()
                        page.close()
                finally:
                    doc.close()
            except InputProblem:
                raise
            except Exception as exc:
                raise InputProblem('PDF 无法可靠读取，请检查是否损坏，或重新导出。') from exc
        else:
            if ext in ('.docx', '.pptx'):
                try:
                    sections = _office(path, ext)
                except InputProblem:
                    raise
                except Exception as exc:
                    raise InputProblem('Office 文档无法读取，请重新导出 PDF。') from exc
            elif ext in ('.txt', '.md'):
                try:
                    text = path.read_text(encoding='utf-8-sig')
                except UnicodeError as exc:
                    raise InputProblem('文字文件不是 UTF-8 编码，请另存为 UTF-8 后上传。') from exc
                if '\x00' in text:
                    raise InputProblem('文字文件含二进制数据。')
                sections = [('文本段落', text)]
            else:
                raise InputProblem('不支持此资料格式。')
            for label, text in sections:
                if not text.strip():
                    continue
                paragraphs = text.splitlines(keepends=True)
                chunk, start = '', 1
                for n, paragraph in enumerate(paragraphs, 1):
                    if len(paragraph) > 16000:
                        raise InputProblem('文字文件含超长单行，请保留合理段落后上传，避免截断公式或题目。')
                    if chunk and len(chunk) + len(paragraph) > 10000:
                        add(sid, f'{label}，行 {start}–{n-1}', chunk)
                        chunk, start = '', n
                    chunk += paragraph
                if chunk:
                    add(sid, f'{label}，行 {start}–{len(paragraphs)}', chunk)
    if not pages:
        raise InputProblem('资料中没有可读取的正文。')
    return {'sources': sources, 'pages': pages}
