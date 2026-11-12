# 明确配置的学科检查（1.5.0）

`course.disciplineChecks` 是 schema v2 的可选规则数组，v1 也能读取。不根据课程名、`disciplines`、表头或单位猜测规则。未配置或数组为空时报告 `not-configured`，不表示已通过全学科认证。规则只检查当前课程里的实际内容块；不接受另复制一份数据或手填的通过结论。

## 实际内容定位

每条规则有唯一非空 `id`、`kind`、`target`，可选非空 `description`。定位结构固定为：

```json
{"targetId":"lesson-1","area":"blocks","blockPath":[0]}
```

`targetId` 为实际小节或题目 ID。小节只接受 `area:"blocks"`；题目接受 `"prompt"` 或 `"answer.blocks"`。`blockPath` 使用零基整数索引，`[2,0]` 表示第 3 块 `details` 里的第 1 块。嵌套只沿 `details.blocks`，最长 32 层，不执行属性表达式、文件路径或脚本。数量规则须指向 `table`，矩阵规则须指向 `matrix`。不存在、重名或类型不匹配的目标均无效。所有行列索引从 0 开始。

## 借贷合计

```json
{
  "id":"journal-1", "kind":"journal_balance",
  "target":{"targetId":"example-1","area":"answer.blocks","blockPath":[1]},
  "accountColumn":0, "debitColumn":1, "creditColumn":2,
  "accounts":["原材料","银行存款"], "decimalPlaces":2
}
```

三列须显式指定且互不相同。可选 `accounts` 检查各行名称是否属于明确科目表；可选 `decimalPlaces` 为 0–100 的整数，限制有效小数位数，尾部多写的零不算超精度。借贷金额须为非负有限十进制数，合计严格相等。空行、缺科目或缺金额报错；另一侧没有发生额时须明确写 `"0"`，空白不自动补零。

通过只表明上述约束成立，不能证明业务处理或科目选择正确，不能据此把学生分录自动判对。

## 行列合计、百分比与频数

```json
{
  "id":"column-total", "kind":"table_sum",
  "target":{"targetId":"lesson-1","area":"blocks","blockPath":[0]},
  "axis":"column", "index":1, "indices":[0,1,2],
  "expected":{"targetId":"lesson-1","area":"blocks","blockPath":[0],"row":3,"column":1},
  "tolerance":"0"
}
```

`axis:"column"` 指定 `index` 列，用 `indices` 选择数据行；`axis:"row"` 指定 `index` 行，用 `indices` 选择数据列。省略 `indices` 表示该轴全部单元格；空数组、重复或越界索引无效。含合计行时应显式选择数据行，期望合计单元格不能同时纳入被加数。

- `table_sum`：必须给 `expected`，可为十进制字面量或以上实际单元格定位；可选 `tolerance` 默认 0。
- `percentage_total`：期望合计固定为 `100`，不接受 `expected`；可显式给非负 `tolerance`，如 `"0.01"`。单元格写 `"33.33"`，不写 `"33.33%"`。0–1 比例应使用 `table_sum` 和 `expected:"1"`，不能猜单位。
- `frequency_total`：`expected` 为明确样本量或实际样本量单元格；频数与样本量均须为非负整数，严格相等，不接受容差。

数量检查使用 Decimal，包含容差边界，不靠二进制浮点近似。建议高精度数值写成字符串，已在上游浮点转换中丢掉的位数不能恢复。接受普通十进制、科学计数法，不执行算式，不删除单位、百分号或千分位分隔符。拒绝缺测、布尔值、NaN、Infinity、无效数字和负容差；单个数字文本最多 4096 字符，十进制指数绝对值不超过 10000。出现缺测时不输出“部分合计已通过”。

## 矩阵形状

```json
{
  "id":"matrix-product", "kind":"matrix_shape", "operation":"multiply",
  "target":{"targetId":"lesson-2","area":"blocks","blockPath":[0]},
  "other":{"targetId":"lesson-2","area":"blocks","blockPath":[1]},
  "result":{"targetId":"lesson-2","area":"blocks","blockPath":[2]}
}
```

- `add`：必需 `other`，两个矩阵同形；可给 `result` 检查结果形状。
- `multiply`：必需 `other`，左列数等于右行数；可给 `result` 检查结果行列数。
- `transpose`：必需 `result`，结果行列数与原矩阵交换；不接受 `other`。
- `square`：只给 `target`，检查行列式所需的方阵条件；不接受 `other` 或 `result`。

空矩阵、参差行或缺测单元格无效。非空数学表达式可作矩阵元素；这里只检查形状，不计算元素、转置值、行列式或证明公式等价。公式语法仍由现有离线 KaTeX 检查，不引入 CAS。

## 报告与构建

`report_discipline_checks(course)` 返回 `status`、配置/通过/失败/无效数量、逐规则 `checks` 和汇总 `errors`。每条结果含实际引用的 `targetIds`、计算观察值，以及 `ruleId`、`location:{targetId,area,blockPath,row?,column?}`、`actual`、`expected`、错误代码与错误范围。`validate_discipline_checks(course)` 返回供构建器阻断的错误字符串。

`validate` 报告与构建后的 `validation.disciplineChecks` 保留完整结果。`fail` 或 `invalid` 阻止完整构建；显式 `--allow-incomplete` 可保留未通过结果并将范围标为 incomplete，不会把规则改为通过。未配置维持 `not-configured`。

规则配置与全部显式引用先预检，不能让已发现的内容错误遮蔽另一个无效定位。若表格或矩阵本身的行列结构已损坏、页面无法显示，即使用 `--allow-incomplete` 也须先修复结构；不会交付会在渲染时崩溃的块。

章级 `disciplineChecks` 只列出实际引用目标位于本章的规则。算术不符、实际单元格缺测等问题阻断关联章节；跨章规则影响所有引用章节。未知规则、非法配置或错误定位无法可靠缩小范围，阻断全局可学习结论。规则与实际内容变化均进入验收绑定，不能复用旧浏览器/视觉结论。原有内容、审校、抽检、离线与视觉状态分别保留。

结果不修改题目答案、自动判分规则、学习记录或语义审校结论。即使明确配置的规则全部通过，资料融合是否准确、业务科目是否合适、统计口径和单位是否正确、数学推导是否成立，仍须按原资料人工审校。
