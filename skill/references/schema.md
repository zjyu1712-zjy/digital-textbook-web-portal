# 数据契约 v2（兼容读取v1）

学习内容与用户记录严格分离。可运行最小例：`tests/fixtures/general.json`；独立来源清单：`tests/fixtures/inventory.json`；原测试源：`general-source.txt`。这是自编通用小样本，不是五课程材料。

## 内容 JSON

- `schemaVersion:2` 用于新制作；v1继续可读，但旧自由文本审校不证明当前内容已核查。`id` 稳定教材身份，不随导出日期/路径/内容版本改变；`version` 内容版本；`title, edition`。
- `scope:{description,completeness:complete|excerpt|incomplete,excluded:[]}`。
- `organization:{mode:textbook|slides|outline|combined,primarySourceIds:[],reason}`；`disciplines:[math|theory|models|accounting|statistics|general]`。
- `sources:[{id,title,role,identity,sha256,locator}]`：role 如 textbook/teacher_slides/outline/solution/exam/auxiliary；定位注明PDF物理页、印刷页或PPT页，不相互混用。
- `chapters:[{id,title,sections:[{id,title,sourceRefs,blocks}]}]`。小节ID兼作知识点跳转；细粒度知识点可拆成有实质讲解的小节。
- `questions:[{id,number,title,kind,origin,version,chapterIds,knowledgeIds,sourceRefs,prompt,parts,answer,grading}]`。
- `origin`: textbook_example / textbook_exercise / teacher_exercise / exam / auxiliary_exercise / ai_supplement，分别统计。
- `parts:[{id,label,fields:[{id,kind,label,...}]}]`。字段 ID 在题内唯一，小问 ID 稳定，不能用数量代替完整字段。
- `answer:{version,provenance:original|teacher|unconfirmed|ai,status:ready|pending|missing,blocks,sourceRefs}`。缺答案也保留说明块。
- `grading:{kind:self}` 默认。可靠单选/多选用choice，数值用numeric；每个作答字段各有一条 `{fieldId,expected,tolerance?}` 规则，并用rationale说明可靠边界。numeric限number/fill字段，expected为有限数字，tolerance为非负有限数字；整数须在±9007199254740991内。choice的参考值须属于实际选项，多选是无重复选项数组。缺项、类型错误、混合主观字段或不可靠答案不得自动判对，改用self或修复规则。不得自动比较主观文本、公式字符串或仅凭分录金额总和平衡判对。
- `exams:[{id,title,instructions:blocks,questionIds:[]}]`。题目原序和父题共同材料保留。
- `coverage:[{sourceItemId,targets:[],status:covered|pending|missing}]`。
- `taskContract:{version:1,goal,basis,sourceUses,chapterPlans,pendingMaterials}` 保存本任务每份资料用途及适用章节。
- `learningMap:[{sourceItemId,disposition,explanationTargets,summaryTargets,emphasisTargets,summaryNote,emphasisNote,evidence}]` 保存实质融合处理。
- `semanticReviews:[{targetIds,reviewer,method,result:pass|pending|fail,evidence,binding:{version:1,fingerprint}}]` 只能填写实际做过的核查；绑定过期不能继续算pass，不由build自动生成结论。
- 上述v2新增字段的枚举、例子、绑定及旧数据升级见 [任务资料约定与审校时效](task-contract-and-review.md)。
- 可选 `independentReview:{required?,plan,sourceRead,records}` 保存先读原文、再对照生成内容的独立抽检；`required:true` 时缺项、过期或失败不能交付完整成果。计划及记录结构见 [独立抽检](independent-review.md)。旧教材不因缺此字段被自动补出通过结论。
- 可选 `chapterChecks` 保存实际浏览器/视觉证据，派生的 `validation.chapterStatus` 分别展示各章内容、审校、抽检和验证范围；见 [章级状态](chapter-status.md)。构建成功不产生功能或视觉通过。
- `issues:[]`；`migrations:{questionAliases:{旧ID:新ID}}` 只用于真实不可避免的ID变更；默认不变。迁移不改写旧快照。
- `acceptance` 为验收说明的内容块数组；结果只写真实测试，明确范围和未验证项。

## 内容块

不接收任意原始HTML。`paragraph/heading:{text}`；`list:{items:[字符串]}`；`math:{tex,display:true}`；`matrix:{rows:[[字符串]]}`；`table:{columns:[字符串],rows:[[字符串]]}`；`details:{title,blocks}`；`image:{path,alt,caption?,sha256}`（v2要求真实图片文件SHA-256，v1可缺省）（相对 --assets 根目录的栅格图片，构建内嵌）；`diagram:{alt,caption,lines:[{points:[[x,y],...]}],labels:[{x,y,text}]}`（640×360坐标，不执行外部代码）。

模型自行把教材公式转为有效 LaTeX；解析扫描矩阵后逐行列核对。文字中的不等号以文本保留。图像不代替可阅读正文；图表源定位写在所在小节或题目。

## 输入字段

`text` 多行；`fill` 单行；`number` 数值文本；`formula` LaTeX输入及离线预览；`choice/multiple` 的 options 为字符串或 `{value,label}`；`matrix/table/journal` 的 columns 为字符串或 `{label,editable:false}`，rows 为二维数组，初始可答单元格留空；只读列放原题给定标签/数值。为分录提供足够行数，多借多贷与业务对应关系不能省略。

numeric接受首尾空格、全角数字/符号、十进制、科学计数法及规范千分位（如1,000）。不自动去掉单位/百分号，不执行分数、算式或十六进制。输入会与转换后的规范十进制值对照，发生静默舍入、上溢或下溢时提示调整，不作为知识性错误提交。容差按十进制系数比较，包含边界。题面仍须声明单位与精度，输入框自动显示格式提示。公式等价表达继续对照自评。

## 独立来源清单

`{source:清单形成依据,items:[{id,sourceId,locator,kind,expectedParts:[]}]}`。
先根据主资料形成，再制作内容；标题不算覆盖，空题干不算题目。kind 表达实际资料项，例如 lesson/definition/proof/figure/example/exercise。自动验证只检查结构/数量和审查记录存在，不能证明原文清单穷尽或答案学术正确。

## 学习记录

IndexedDB `digital-textbook:<book.id>`，结构版本独立于书的内容version。表：drafts / attempts / attachments / progress / notes / events / versions / settings。错题标记与掌握状态追加到 events，完整备份仍为formatVersion 1，不增加数据库版本；详见 [错题本](mistakes.md)。
草稿 `{id,courseId,questionId,questionVersion,answerVersion,answers,attachments,rev,viewedAnswer,startedAt,updatedAt}`；提交是追加且含完整 questionSnapshot/referenceAnswer、版本、时间、判定。附件存Blob与内容hash。自评与看答案事件追加，不修改提交事实。
完整备份 `format:digital-textbook-backup,formatVersion:1,course:{id,version},tables`；跨教材拒绝，冲突整次中止。旧系统备份不直接冒充此格式，需受测试的专用迁移工具；本Skill未内置五种旧备份的一键迁移器。

存储能力区分可读写、只读、不可用。只读时保留已有历史与附件的读取和完整备份导出，禁用写入/提交/导入，不显示保存成功；内存未保存草稿另行导出，不混入声称已保存的完整备份。现有学习记录和备份结构不变。判定记录可新增status（correct/incorrect/self），旧记录的result文本和快照保持原样；输入格式错误不追加提交，缺判分依据不产生正确判定。

行内公式保持在句子中：`{"type":"paragraph","runs":[{"type":"text","text":"当 "},{"type":"math","tex":"x<3"},{"type":"text","text":" 时成立。"}]}`。runs只接受text/math；禁止插入原始HTML。独立推导用math块。所有行内公式同样在构建时严格校验。
