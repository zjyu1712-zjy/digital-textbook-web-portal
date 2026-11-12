# 任务资料约定、融合证据与审校时效

新建课程使用 `schemaVersion:2`。已有v1内容仍可读取和构建，但其自由文本审查记录标为 `legacy-unverified`，不冒充本轮已核查。升级只改工作副本，保留书ID、原题/字段ID、答案版本及旧快照；不得为升级清空学习记录。

## 先保存本任务的资料用途

在 `course.json.taskContract` 中记录已经从用户请求、同项目约定和实际资料确认的信息。不要因必须有结构化字段而再次询问已明确事项；只有会改变学习主线的未决问题才需确认。下例是自编配置，不是所有任务的默认。

```json
{
  "version": 1,
  "goal": "按教材顺序学习，课堂案例用于解释概念",
  "basis": "本次用户要求：以教材为主，课件补例证",
  "sourceUses": [
    {"sourceId":"book","usage":"primary","chapterIds":["ch1"],"purpose":"决定知识顺序并提供完整定义"},
    {"sourceId":"slides","usage":"example","chapterIds":["ch1"],"purpose":"案例进入对应知识点，不改变教材主线"}
  ],
  "chapterPlans": [
    {"chapterId":"ch1","mode":"textbook","primarySourceIds":["book"],"emphasis":"依据用户学习目标，重点比较概念的适用条件"}
  ],
  "pendingMaterials": []
}
```

`usage` 可为 `primary`（主线）、`explanation`（补解释）、`example`（补例证）、`practice`（题目/解析）、`reference`（仅存档或对照）。同一资料可在不同章节承担不同作用；同一资料在同一章只有一个usage，复合用途写入purpose。所有已提供资料都要说明至少一个用途，所有制作章节都要有chapterPlan；章计划中的主资料必须与该章primary用途对应。明确约定尚待补充的资料写入pendingMaterials，不虚构来源文件。

`organization` 仍保存全书模式和主资料概括，须与任务约定一致。`classify` 读取现有organization及taskContract；加 `--chapter ch1` 查看该章约定。未确定主次的混合资料返回 `materialMode:null, needsDecision:true`，不因存在PPT就选slides。旧输入中的 `sources[].primary` 仅兼容读取并提示，后续统一保存到正式字段。

## 每个资料条目怎样进入学习内容

保留原 `coverage`；v2另在 `learningMap` 中为独立来源清单的每个条目保存一行：

```json
{
  "sourceItemId": "slide-case-1",
  "disposition": "integrated",
  "explanationTargets": ["ch1-concept"],
  "summaryTargets": ["ch1-recap"],
  "emphasisTargets": [],
  "summaryNote": "章末回顾概念和案例之间的对应关系",
  "emphasisNote": "作为说明案例，不新增教师未要求的考试重点",
  "evidence": "课件第2页的两种情形已融入概念小节的比较讲解"
}
```

- `integrated`：实际讲解目标必填，且目标须含可读解释；只有标题、原页图片或独立公式不能代替讲解。总结和重点各自有目标，或写明不单独列出的处理理由，不要求所有细节重复进入总结。
- `reference-only`：仅用于任务约定明确为reference的资料；explanationTargets须完整列出该来源条目在coverage中的所有位置，且涉及的章节都明确为reference，不能用它规避原本要求纳入学习的资料。
- `pending`：尚未完成融合，不能作为完整成果通过验收。

所有目标沿用真实小节或题目ID，不凭空创建对应关系。脚本能发现目标不存在、只附原页、用途不符等结构问题；“是否解释准确、概念有无遗漏、重点是否恰当”仍须逐项对读，不能由字数或指纹自动判断。

## 审查结果必须对应当前内容

v2的 `semanticReviews` 除原有targetIds、reviewer、method、result和evidence外，增加：

```json
"binding": {"version":1,"fingerprint":"对当前目标及其相关证据计算的SHA-256"}
```

指纹绑定实际目标内容、相关来源与独立清单、融合记录，以及任务资料约定。正文、题目/答案、相关来源标识或摘要、融合处理、资料用途变化时，旧pass不再算当前有效；无关的外观调整不应冒充知识内容变化。来源文件更新后必须先重算其真实摘要，保留伪旧摘要会使任何时效检查失去依据。v2图片块另须记录真实文件sha256并进入目标指纹；build比对本地文件字节，即使路径相同也拒绝摘要不符的图片，--allow-incomplete不能绕过。review-state只核对传入的课程和来源清单快照，不宣称自动重新读取全部外部源文件。

题目所属试卷的统一说明或题设、成员与顺序、标题和版本及其来源引用也计入依赖；修改整卷条件后须重新核对相关题目。

工作顺序是：完成讲解与融合记录→实际对读并记录发现/修复→计算当前绑定→把真实审查结论和绑定一起写入对应记录→检查状态。下面命令只计算绑定，不创建pass、不修改课程：

```sh
python3 /技能绝对路径/scripts/pipeline.py review-binding /工作区/course.json \
  --inventory /工作区/source-inventory.json --targets ch1-concept ch1-recap \
  --out /工作区/checks/review-binding.json
python3 /技能绝对路径/scripts/pipeline.py review-state /工作区/course.json \
  --inventory /工作区/source-inventory.json --out /工作区/checks/review-state.json
```

`review-state`：当前所需审查全部通过时退出0；旧v1记录尚无当前绑定证据时退出2；缺项、失败或过期时退出1。它不代替完整结构validate。`validate/build`对v2同时检查任务约定、融合映射和审校时效；build不会自动修改任何审校结论。来源页显示任务资料用途、融合处理和当前审校状态，旧审查原文保留但与当前状态分开。

## 旧教材升级

在独立副本中添加taskContract与learningMap，将schemaVersion改为2。已有审查记录保留为历史依据，不批量自动加绑定：实际复核相关内容后，再记录新的审查结论与绑定。新旧版本的书、题目、字段和存储身份保持不变；用隔离浏览器验证旧草稿及提交快照恢复。真实私有课程不得作为技能包内的测试样本发布。
