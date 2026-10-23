# 数据契约 v1

学习内容与用户记录严格分离。可运行最小例：`tests/fixtures/general.json`；独立来源清单：`tests/fixtures/inventory.json`；原测试源：`general-source.txt`。这是自编通用小样本，不是五课程材料。

## 内容 JSON

- `schemaVersion:1`；`id` 稳定教材身份，不随导出日期/路径/内容版本改变；`version` 内容版本；`title, edition`。
- `scope:{description,completeness:complete|excerpt|incomplete,excluded:[]}`。
- `organization:{mode:textbook|slides|outline|combined,primarySourceIds:[],reason}`；`disciplines:[math|theory|models|accounting|statistics|general]`。
- `sources:[{id,title,role,identity,sha256,locator}]`：role 如 textbook/teacher_slides/outline/solution/exam/auxiliary；定位注明PDF物理页、印刷页或PPT页，不相互混用。
- `chapters:[{id,title,sections:[{id,title,sourceRefs,blocks}]}]`。小节ID兼作知识点跳转；细粒度知识点可拆成有实质讲解的小节。
- `questions:[{id,number,title,kind,origin,version,chapterIds,knowledgeIds,sourceRefs,prompt,parts,answer,grading}]`。
- `origin`: textbook_example / textbook_exercise / teacher_exercise / exam / auxiliary_exercise / ai_supplement，分别统计。
- `parts:[{id,label,fields:[{id,kind,label,...}]}]`。字段 ID 在题内唯一，小问 ID 稳定，不能用数量代替完整字段。
- `answer:{version,provenance:original|teacher|unconfirmed|ai,status:ready|pending|missing,blocks,sourceRefs}`。缺答案也保留说明块。
- `grading:{kind:self}` 默认。可靠单选/多选用 choice，单一数值用 numeric；规则 `{fieldId,expected,tolerance?}`；还需 `rationale` 说明可靠边界。不得自动比较主观文本/公式字符串/分录金额总和。numeric 对千分位/单位/表达式未实现解析，题面明确要求纯数值；否则用self。
- `exams:[{id,title,instructions:blocks,questionIds:[]}]`。题目原序和父题共同材料保留。
- `coverage:[{sourceItemId,targets:[],status:covered|pending|missing}]`。
- `semanticReviews:[{targetIds,reviewer,method,result:pass|pending|fail,evidence}]` 只能填写实际做过的核查，不由build自动伪造。
- `issues:[]`；`migrations:{questionAliases:{旧ID:新ID}}` 只用于真实不可避免的ID变更；默认不变。迁移不改写旧快照。
- `acceptance` 为验收说明的内容块数组；结果只写真实测试，明确范围和未验证项。

## 内容块

不接收任意原始HTML。`paragraph/heading:{text}`；`list:{items:[字符串]}`；`math:{tex,display:true}`；`matrix:{rows:[[字符串]]}`；`table:{columns:[字符串],rows:[[字符串]]}`；`details:{title,blocks}`；`image:{path,alt,caption?}`（相对 --assets 根目录的栅格图片，构建内嵌）；`diagram:{alt,caption,lines:[{points:[[x,y],...]}],labels:[{x,y,text}]}`（640×360坐标，不执行外部代码）。

模型自行把教材公式转为有效 LaTeX；解析扫描矩阵后逐行列核对。文字中的不等号以文本保留。图像不代替可阅读正文；图表源定位写在所在小节或题目。

## 输入字段

`text` 多行；`fill` 单行；`number` 数值文本；`formula` LaTeX输入及离线预览；`choice/multiple` 的 options 为字符串或 `{value,label}`；`matrix/table/journal` 的 columns 为字符串或 `{label,editable:false}`，rows 为二维数组，初始可答单元格留空；只读列放原题给定标签/数值。为分录提供足够行数，多借多贷与业务对应关系不能省略。

## 独立来源清单

`{source:清单形成依据,items:[{id,sourceId,locator,kind,expectedParts:[]}]}`。
先根据主资料形成，再制作内容；标题不算覆盖，空题干不算题目。kind 表达实际资料项，例如 lesson/definition/proof/figure/example/exercise。自动验证只检查结构/数量和审查记录存在，不能证明原文清单穷尽或答案学术正确。

## 学习记录

IndexedDB `digital-textbook:<book.id>`，结构版本独立于书的内容version。表：drafts / attempts / attachments / progress / notes / events / versions / settings。
草稿 `{id,courseId,questionId,questionVersion,answerVersion,answers,attachments,rev,viewedAnswer,startedAt,updatedAt}`；提交是追加且含完整 questionSnapshot/referenceAnswer、版本、时间、判定。附件存Blob与内容hash。自评与看答案事件追加，不修改提交事实。
完整备份 `format:digital-textbook-backup,formatVersion:1,course:{id,version},tables`；跨教材拒绝，冲突整次中止。旧系统备份不直接冒充此格式，需受测试的专用迁移工具；本Skill未内置五种旧备份的一键迁移器。

行内公式保持在句子中：`{"type":"paragraph","runs":[{"type":"text","text":"当 "},{"type":"math","tex":"x<3"},{"type":"text","text":" 时成立。"}]}`。runs只接受text/math；禁止插入原始HTML。独立推导用math块。所有行内公式同样在构建时严格校验。
