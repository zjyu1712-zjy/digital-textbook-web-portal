"""Build a clearly synthetic seven-chapter fixture with three missing chapters."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from test_usable_chapters import course_with_chapters, leave_pending, rereview
import pipeline


def create(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    course, inv = course_with_chapters()
    course.update(id="partial-browser-fixture", title="分批交付 · 自编测试", edition="synthetic", version="1",
                  disciplines=["general"], exams=[])
    course["scope"] = {"completeness":"incomplete", "description":"仅用于界面验收：七章中第三至第五章待补。"}
    course["organization"]["reason"] = "Synthetic fixture for actual browser verification."
    for source in course["sources"]:
        source.update(title="自编资料 "+source["id"], identity="synthetic test source", locator="test fixture")
    for index, chapter in enumerate(course["chapters"], 1):
        chapter["title"] = "第"+str(index)+"章 自编验收"
    leave_pending(course, inv, [3, 4, 5])
    for chapter in course["chapters"]:
        if chapter.get("pending"):
            chapter["pending"]["reason"] = "本章原资料尚未提供，补齐后再整理。"
    rereview(course, inv)
    for name, data in [("course.json",course),("inventory.json",inv)]:
        (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    report = pipeline.build(course, inv, folder/"partial.html", folder, allow_incomplete=True,
                            size_report=folder/"resources.json")
    assert report["chapterStatus"]["learningRange"]["prefixChapterIds"] == ["ch1","ch2"]
    assert report["chapterStatus"]["learningRange"]["readyChapterCount"] == 4
    (folder/"build.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return folder/"partial.html"


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    print(create(parser.parse_args().output))
