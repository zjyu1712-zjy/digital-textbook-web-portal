# 章级状态与验证范围

章级状态由构建器派生在 `validation.chapterStatus`，不从一句“全书通过”推断各章完成。首页卡片仅显示内容、审校和抽检的短状态；章节开头的详情默认折叠；来源页显示各章对照表与证据。

- **内容整理**：按独立原资料清单检查本章来源条目的覆盖位置。未映射条目仍计入；无法归章的条目另列。数量齐全不证明讲解正确。
- **审校**：汇总本章实际目标的语义审校时效。正文、题目或相关资料变更后，不继续显示旧审校有效。旧 v1 自由文本记录为待核对。
- **独立抽检**：显示本章入样、已审数量与结论。样本通过只代表所列样本，未入样不写通过。见 [独立抽检](independent-review.md)。
- **离线功能、视觉检查**：分别汇总实际记录的目标范围。构建成功不自动产生浏览器或视觉通过；只测一章或一个题目不能扩大到其他内容。

## 保存真实验收记录

可选顶层 `chapterChecks` 保存实际完成的检查。旧教材没有它仍可使用，页面显示未单独验证。每条记录的结构为：

```json
{
  "chapterId":"ch1",
  "kind":"offline",
  "result":"pass",
  "reviewer":"实际执行检查者",
  "method":"浏览器及版本、file://断网、宽窄屏尺寸和实际操作",
  "evidence":"具体结果和局限；不能只写通过",
  "checkedAt":"2026-11-12T10:00:00+08:00",
  "targetIds":["真实检查的小节或题目ID"],
  "checks":["实际执行的检查名"],
  "artifactSHA256":"实际测试HTML文件的64位SHA-256",
  "binding":{"version":1,"fingerprint":"当前章节绑定","rendererFingerprint":"当前构建器和显示资源绑定"}
}
```

`kind` 为 `offline` 或 `visual`；`result` 为 `pass`、`fail` 或 `pending`。targetIds 只列实际检查内容。宽窄屏逐章打开、核对小节与布局，可以记录这些小节的打开/布局检查；并不表示每道题都实际作答。视觉范围只列截图中实际可见并复核的内容。具体操作在 checks、method 和 evidence 中保留。

`chapter-binding` 只计算绑定，不创建检查结论：

```sh
python3 /技能路径/scripts/pipeline.py chapter-binding /工作区/course.json \
  --inventory /工作区/source-inventory.json --chapter ch1 --out /工作区/checks/ch1-binding.json
python3 /技能路径/scripts/pipeline.py chapter-state /工作区/course.json \
  --inventory /工作区/source-inventory.json --out /工作区/checks/chapter-state.json
```

章节内容、相关资料、任务约定、原资料清单或教材版本改变，内容绑定即过期；显示资源或构建器变化，渲染绑定即过期。旧记录保留但不计入当前验证范围。当前绑定下仍有 fail/pending 时，另写 pass 不能覆盖它。修复内容/组件并重新检查后，可追加新绑定记录。

加入记录与验收说明不会改变内容绑定，但会改变 HTML 文件字节。记录保留当时实际测试文件的摘要；嵌入证据后仍须对最终文件复测，最终摘要与报告存工作目录，避免为了匹配摘要无限重建。脚本只核对记录结构、范围与时效，无法技术证明检查者确实做过这些操作。

`chapter-state` 退出 0 仅表示成功生成状态报告，不表示每章验证通过；必须读取各维度状态。不得手工改 `validation.chapterStatus` 把未验证状态涂成通过，构建时会重算。
