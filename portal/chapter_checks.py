"""Bind only actually executed browser route checks to their chapter targets."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def browser_chapter_records(pipeline, course, inventory, report, html_path):
    """Shared storage tests and unscoped screenshots do not certify each chapter."""
    if report.get('status') != 'pass':
        return []
    scope = report.get('scope')
    if not isinstance(scope, dict):
        return []  # Historical or injected reports without scope cannot make chapter claims.
    checks = report.get('checks', [])
    if not any(c.get('name') == 'all-routes-layout' and c.get('status') == 'pass'
               for c in checks if isinstance(c, dict)):
        return []
    path = Path(html_path).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if (report.get('sha256') != digest or report.get('file') != str(path)
            or report.get('opening') != 'file://' or not report.get('browser')):
        raise ValueError('章级检查报告与实际离线文件不匹配。')
    chapters = {c['id']: c for c in course['chapters']}
    questions = {q['id']: q for q in course['questions']}
    selected = {}
    for name, allowed in [('chapters', chapters), ('questions', questions),
                          ('exercisedQuestions', questions)]:
        ids = scope.get(name, [])
        if (not isinstance(ids, list) or any(not isinstance(x, str) for x in ids)
                or len(ids) != len(set(ids)) or not set(ids) <= set(allowed)):
            raise ValueError('章级检查范围包含无效或未知的目标。')
        selected[name] = set(ids)
    if not selected['exercisedQuestions'] <= selected['questions']:
        raise ValueError('作答检查范围没有对应已打开题目。')
    at = datetime.now(timezone.utc).isoformat()
    rows = []
    for chapter_id, chapter in chapters.items():
        section_ids = [s['id'] for s in chapter['sections']] if chapter_id in selected['chapters'] else []
        question_ids = sorted(qid for qid in selected['questions']
                              if chapter_id in questions[qid]['chapterIds'])
        targets = section_ids + question_ids
        if not targets:
            continue
        exercised = sorted(qid for qid in question_ids if qid in selected['exercisedQuestions'])
        rows.append({
            'chapterId': chapter_id, 'kind': 'offline', 'result': 'pass',
            'reviewer': '浏览器自动检查 / ' + str(report['browser']),
            'method': 'file:// 断网环境中逐章、逐题打开；1440/390 像素核对章节小节、作答控件、公式、图片及横向布局。',
            'evidence': ('本章实际检查 ' + str(len(section_ids)) + ' 个小节和 ' + str(len(question_ids))
                         + ' 道题的页面结构与布局。实际输入并刷新恢复仅覆盖题目：'
                         + ('、'.join(exercised) if exercised else '无')
                         + '。共享存储测试不扩展为本章所有题的完整作答验证；截图仅作全局可见范围核查。'),
            'checkedAt': at, 'targetIds': targets, 'checks': ['all-routes-layout'],
            'artifactSHA256': digest,
            'binding': pipeline.chapter_binding(course, inventory, chapter_id),
        })
    return rows
