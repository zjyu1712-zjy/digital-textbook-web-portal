# 错题导出与独立复习

错题导出使用当前筛选出的历史题目组。题目或解析已修改、改名或删除时，仍读取每次提交保存的 `questionSnapshot` 和 `referenceAnswer`，不能换成当前题库中的内容。导出不改变判分、错题归集或掌握状态规则。

## 格式与边界

| 格式 | 用途 | 保留内容 |
| --- | --- | --- |
| JSON | 留存完整错题记录 | 原有 `digital-textbook-mistakes` 第 1 版格式；相关作答、附件及事件 |
| Markdown | 阅读、笔记和打印 | 当时题设、作答要求、解析、来源、版本、历次作答；文末保留完整错题 JSON |
| CSV | 表格筛选与统计 | 每个历史版本一行；题设、解析、次数与状态；完整快照、作答、附件和事件另存为结构化 JSON 单元格 |
| 单文件 HTML | 离线复习 | 旧题、旧解析、图片与公式；独立文本重做、手动复习状态、原错题与本页结果导出 |

以上均为筛选出的错题记录，不是完整学习备份，不能通过主教材的“完整备份导入”恢复。Markdown 的图片以 data URI 保存；查看器不支持时，可从文末 JSON 的附件中取出原图片。CSV 的复杂题型保留 JSON 结构，不转为 `[object Object]`。部分表格软件对单元格长度有限制，含大量图片或长篇解析时，以 JSON 或 HTML 为完整阅读入口。

HTML 复习页使用每次导出生成的独立标识存储新练习，不访问主教材 IndexedDB，不自动回写主教材。它保留本页的文本练习与“待复习／已掌握”选择，但不复制主教材全部作答控件、不自动判分、不接收结果导入。原题的选择项和表格要求仍可阅读。重做正确与否由学习者对照解析自评，原始错答和原教材掌握状态不被覆盖。

复习页的浏览器保存受 `file://` 环境限制。存储不可用或配额失败时，页面明确提示仅保留在当前页内存，仍可导出包含草稿、练习记录和原错题数据的复习结果。换浏览器、移动文件或关闭未可靠保存的页面前，应先导出结果。该轻量复习页不承诺多标签页并发编辑合并；同一导出文件宜在一个页面中复习。

## 集成接口

主教材只加载以下两个模块，不执行独立页启动函数：

1. `assets/mistake_review.js` 定义 `DTHMistakeReview`。
2. `assets/mistake_exports.js` 定义 `DTHMistakeExports`。

取得一次完整备份后，从该备份重新归集、筛选，再创建导出包：

```javascript
const backup = await DTH.db.exportBackup({
  id: course.id, title: course.title, version: course.version
});
const groups = await DTHMistakes.collect(
  course, backup.tables.attempts, backup.tables.events
);
const chosen = filteredMistakes(groups);
const bundle = DTHMistakeExports.prepare(course, backup, chosen, filters);

// 原 JSON 格式保持不变。
const original = bundle.notebook;
const markdown = DTHMistakeExports.toMarkdown(bundle);
const csv = DTHMistakeExports.toCSV(bundle);
const html = DTHMistakeExports.toHTML(bundle, {
  katexSource: document.getElementById('math-runtime').textContent,
  katexCSS: document.getElementById('math-style').textContent
});
DTHMistakeExports.download(html, '错题复习.html', 'text/html;charset=utf-8');
```

`prepare` 为导出做只读复制；遇到缺失附件、混合版本或与备份不一致的记录时拒绝生成不完整结果。输出包的 `exportId` 只用于独立复习页，不改变原 JSON 的字段结构。导出过程中禁止从远端或原图片路径重新取图，图片字节必须已在历史快照或附件备份中。

主 HTML 中 KaTeX 源码与内嵌字体 CSS 各保存一份，导出时读取已有节点，不新增重复的资源容器。独立 HTML 则携带自己的显示资源。缺少数学资源时保留 LaTeX 文本并显示明确提示；不是成功完成公式显示验收。`toHTML` 的资源参数只能由构建器提供本地可信代码，不可接收课程文本或用户输入作为可执行代码。

## 安全与保真

- 所有历史文本作为文本输出；不执行 Markdown 中的 HTML。HTML 的 JSON 数据转义尖括号，避免 `</script>` 结束数据标签。题目图形只接受现有结构化点线数据，附件只显示受支持的内嵌位图。
- 独立 HTML 的 CSP 禁止网络、表单提交与外部基地址；公式使用 `trust:false`，不接受远程字体或样式导入。
- CSV 使用 UTF-8 BOM、CRLF、双引号包围及双引号加倍。以 `=、+、-、@` 开头的危险非数字文本，以及开头的制表／换行符，加单引号防止表格软件将其当作公式。检查会跳过前导空白和常见不可见控制符。完整十进制和科学计数法数字字符串（如 `-100`、`-1.2e-3`）保持原值。此规则应用于所有单元格；结构化内容以 JSON 文本保存，嵌套文本不会作为单独公式单元格输出。
- 来源定位来自历史题目与答案的 `sourceRefs`；来源显示名称使用导出时可用的来源目录。原资料文件本身不打包进错题页；需要逐页核对时应保留原教材及其来源审查资料。

## 验证

```text
node tests/mistake-exports.cjs
node tests/mistake-exports-ui.cjs path/to/self-authored-demo.html path/to/report
```

浏览器验收必须使用集成了实际导出按钮的自编示例，使用隔离浏览器数据，并在 `file://`、离线条件下执行。测试真实下载 JSON、Markdown、CSV 和 HTML，核对两代题目、已删除旧题、图片与记录；随后打开下载的复习页，检查折叠、公式、图片、宽窄屏、练习保存、重新打开、结果导出、存储失败和主教材记录不变。自动报告的 `visualReview` 初始仍为待人工看图，不能将截图生成自动当作视觉验收完成。
