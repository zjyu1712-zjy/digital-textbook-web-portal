# 可离线试用的自编示例

[下载 demo-general.html](https://github.com/zjyu1712-zjy/digital-textbook-html/releases/download/v1.5.0/demo-general.html)，保存后用浏览器打开。可阅读两章、完成六道题、查看历次记录和错题本，导出Markdown、CSV或独立离线复习页，再从“备份与恢复”下载完整备份。文件自身不含任何真实学习记录；截图里的作答由隔离测试生成。

示例涵盖资料主次与融合、文字/数值/单选/公式/表格输入、解析标记及隐藏、历史快照与备份。没有整卷真题，不代表整本教材、所有题型或学科已通过验收。公式与表格题采用对照自评。

原文为本项目自编：[标签与记录](../tests/fixtures/general-source.txt)、[课堂编号案例](../tests/fixtures/fusion-supplement.txt)、[旧模板对照](../tests/fixtures/fusion-reference.txt)、[测量与平均值](measurement-source.txt)。数据在[demo-course.json](demo-course.json)，独立清单在[demo-inventory.json](demo-inventory.json)。2026-11-12，维护者对读了四份原文及本示例全部讲解、题目与答案；另一未看过生成内容的审阅上下文先读原文，再核对从11个来源条目中抽取的6个样本。抽检发现“同类对象”放宽了原文“对象、单位和测量口径一致”的前提，已修正并复核受影响的讲解与题目。当前6个样本通过，原失败记录保留为过期记录；该结果不代替其他教材的全文审校。

## 本轮实际验证范围

| 环境 | 打开方式 | 写入/重开/备份 | 日期与范围 |
| --- | --- | --- | --- |
| macOS，Microsoft Edge 157（自动化隔离用户目录） | file://，网络断开 | 示例实际作答、下载完整备份与重复导入通过；通用回归另验证浏览器关闭重开、历史及图片恢复 | 2026-11-12；宽1440及390像素 |
| 同环境，注入存储写入/读回故障 | file://，网络断开 | 只读时历史与附件可导出；不能提交或导入；刷新恢复后可写 | 2026-11-12；合成故障回归 |
| Windows Server 2025 / Playwright Chromium 151 | file://，断网 | 1.4.0：作答、重开、备份、故障和升级均通过；1.5.0另列工作流 | [实际记录](../references/windows-validation.md) |
| Safari、Firefox | 未执行本轮成品浏览器测试 | 未验证 | 不按品牌推断成功或失败 |

最终示例专项8项、错题本专项17项、多格式导出与独立复习专项7项、章级状态专项9项检查通过；通用离线检查18项通过、1项因示例没有整卷而不适用，20个字体全部实际离线加载。上一版1.4.0已有实际旧版迁移10项通过；1.5.0迁移由当前Windows工作流另行验证。下方14张截图均实际查看，未见公式缺字、提示遮挡或整页横向溢出。章级记录仅列实际核查范围：两章全部阅读小节及题目页面完成自动布局检查，视觉记录覆盖阅读小节，未扩展成全部题目已逐页目视检查。HTML离线存储仍受浏览器与文件入口隔离影响，换入口前先导出备份；本地HTTP与file://也是不同的验证范围。

| 页面 | 宽1440像素 | 宽390像素 |
| --- | --- | --- |
| 章节阅读 | [查看](screens/chapter-1440.png) | [查看](screens/chapter-390.png) |
| 公式作答 | [查看](screens/formula-1440.png) | [查看](screens/formula-390.png) |
| 历次记录 | [查看](screens/history-1440.png) | [查看](screens/history-390.png) |
| 备份与恢复 | [查看](screens/backup-1440.png) | [查看](screens/backup-390.png) |
| 错题本（合成作答） | [查看](screens/notebook-1440.png) | [查看](screens/notebook-390.png) |
| 章级状态（展开） | [查看](screens/status-1440.png) | [查看](screens/status-390.png) |
| 独立离线复习页（自编测试错题） | [查看](screens/review-1440.png) | [查看](screens/review-390.png) |

## 从公开数据重建

将路径替换为实际安装目录和独立工作目录：

```sh
python3 /技能目录/scripts/pipeline.py build /技能目录/examples/demo-course.json \
  --inventory /技能目录/examples/demo-inventory.json \
  --out /工作目录/demo-general.html
node /技能目录/tests/demo.cjs /工作目录/demo-general.html /工作目录/checks/demo
```

公式构建需要Node；浏览器检查还需本地Playwright与Chromium系浏览器，可指定NODE_BINARY、PLAYWRIGHT_MODULE和BROWSER_EXECUTABLE。测试使用临时浏览器数据并在结束后删除；报告和截图留在指定检查目录，不包含真实教材或用户资料。

本示例声明1条实际表格合计规则：800+1000+1200=3000，只验证该关系，不把未配置的会计/其他统计/矩阵规则计为通过。独立复习页的新文字练习及手动状态与主教材分开，不自动判分或回填；原错题数据始终保留。
