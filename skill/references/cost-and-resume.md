# 规模、用量与恢复边界

估算器只读本地数字和日志，不联网、不调用模型，也不查询或默认采用任何模型价格。调用量可以由当前转换流程计数；分钟、tokens 与费用必须有相应阶段的真实观察或使用者明确提供的假设。缺信息显示 `unknown`/`null`，不显示为 0。

## 先估调用量

运行 `scripts/estimate_work.py estimate 范围.json --out 估算.json`。范围示例：

```json
{
  "pageCount": 30,
  "includedPageCount": 24,
  "chapterCount": 2,
  "unitCount": 4,
  "sampleCount": 6,
  "maxModelCalls": 300,
  "spentModelCalls": 0
}
```

`pageCount` 是实际提取的原页或文字段数，不从文件字节数猜页数。`includedPageCount` 是章节处理单元实际涉及的不同原页数；未给时暂按全部纳入并明确标记这个假设。章节按原资料组织，不按八页硬切；八页只是每个处理单元的上限。同一原页可能含多个小节，因此不能从页数推定单元数上限。

令 P 为页/文字段数、U 为计划单元数、S 为实际选择的抽检样本数：

| 阶段 | 无内容修复时的逻辑请求 | 当前最多三轮单元修复 |
| --- | ---: | ---: |
| 原资料逐页清单 | P | P |
| 章节与资料用途规划 | 1 | 1 |
| 逐单元生成 | U | 3U |
| 逐单元对照原页核查 | U | 3U |
| 全局覆盖核查 | 1 | 1 |
| 独立抽样先读原页 | S | S |
| 独立抽样对照生成结果 | S | S |
| 实际截图视觉核查 | 1 | 1 |
| 合计 | P + 2U + 2S + 3 | P + 6U + 2S + 3 |

这些是沿当前流程成功完成的条件计数，不是对任意资料的完成保证。不可辨认、原资料缺项、抽检或视觉失败可能提前停止。网络层单个请求最多尝试三次，另列网络尝试上界；HTTP 失败、等待和可能发生的计费不等同于成功回复。

在计划或样本清单尚未生成时，U/S 的上界为未知。估算器只给 `U ≥ max(章节数, ceil(纳入页数/8))` 等可证明下界；完整抽检至少一项，不拿固定百分比假充已选样本。配置调用限额不会被当成“这么多次一定能完成”，低于必要下界会提示；恢复任务时要提供已经消耗的 `spentModelCalls`。网页端在原资料读取后、章节规划后、抽样计划确定后刷新 P/U/S，并从剩余流程估算中排除确已完成的阶段；已用网络尝试仍计入任务总限额。

API 的 `completed_stages`（CLI 可重复传 `--completed-stage inventory --completed-stage plan`）只接受确已结束的完整阶段，不接受“已经看过章节”作为依据。输出每阶段的 `fullLogicalRequests` 保留全流程范围，`logicalRequests` 与成功回复、耗时和费用的条件估计只算剩余阶段。不能在同一个已完成阶段上再次扣除缓存命中。

## 明确条件后估时长与费用

`--calibration` 接收逐阶段观察，`--prices` 接收使用者提供的单价。例如：

```json
{
  "kind": "user-supplied",
  "basis": "使用者对同一模型与类似处理单元提供的样本",
  "stages": {
    "inventory": [{"inputTokens": 1200, "outputTokens": 300, "elapsedSeconds": 8.5}],
    "generation": [{"inputTokens": 4500, "outputTokens": 2000, "elapsedSeconds": 25}]
  }
}
```

以上只是输入格式示意，不是项目实测基线。其余阶段未提供观察时，总 tokens、时长和费用仍为未知。完整阶段名为 `inventory`、`plan`、`generation`、`review`、`global-review`、`independent-source`、`independent-compare`、`visual-review`。tokens 要非负整数，秒数要有限非负数；测试替身观察不可作为真实模型校准。

价格格式为 `{"currency":"使用者指定币种","inputPerMillion":每百万输入价格,"outputPerMillion":每百万输出价格}`。估算按该平价口径计算，不猜税费、阶梯价或缓存折扣。观察的最小/最大值只形成条件范围，不是统计置信区间；输入图片、输出长度、模型设置改变时应重新测量。

输出中的 `successfulResponseEstimates` 仅估成功回复。失败请求费用、重试等待、提取/构建/浏览器/排队时间单列为未知开销，不能把成功回复秒数当作整本教材交付时间。原始运行日志里有本地步骤耗时也应单独列出，不能把测试替身的运行时间外推为 300 页真实模型转换时长。

## 从实际日志建立基线

```sh
python3 /技能目录/scripts/estimate_work.py baseline /任务目录/model-usage.json --out /工作目录/用量基线.json
```

只接收明确文件路径。输出记录每份日志的 SHA-256、逐条来源与索引、已知 tokens 和耗时、缺失计量、失败与本地缓存命中。支持 OpenAI `input_tokens/output_tokens` 与兼容接口 `prompt_tokens/completion_tokens`；只有总数时不猜输入/输出拆分。新计量日志推荐：

```json
{
  "formatVersion": 2,
  "provider": "实际服务商",
  "model": "实际模型标识",
  "skillFingerprint": "实际技能摘要",
  "calls": 2,
  "usage": [
    {"stage":"unit:u1:attempt:0","status":"failed","attemptIndex":1,"elapsedSeconds":2,"tokens":null},
    {"stage":"unit:u1:attempt:0","status":"success","attemptIndex":2,"elapsedSeconds":9,"tokens":{"input_tokens":1000,"output_tokens":500}},
    {"stage":"unit:u1:attempt:0","status":"cache-hit","elapsedSeconds":0.01}
  ]
}
```

这也只是字段说明。`calls` 只计实际网络尝试，本地缓存命中不增加它。`testDouble:true` 的整份日志或单条记录从真实校准中排除。旧日志只有成功回复，且 `calls` 大于记录数时，差额是“未分类尝试”，不能直接称为失败或计为零开销。未记录耗时则保留未知。网络尝试编号从 1 开始，包含重试；另有全任务递增的 `networkSequence`。请求发出前先落盘 `pending` 并扣调用次数；如果进程中断，该结果保留未确定，不自动改判失败或返还额度。成功、失败与缓存命中的耗时分别记录，失败等待和退避不会混进成功请求基线。

旧日志迁移时保留原 `calls`，历史缺失的模型身份与耗时为 null，并用 `legacyHistoryComplete:false` 保留不完整历史状态。每条新记录绑定实际请求的服务商、模型与技能摘要；日志只记录允许的计量字段，不保存提示词、原文、密钥或完整错误响应。缓存存在但调用记录缺失时会停止核对，不把已用额度重置为零。

不同模型、服务商或技能摘要的观察分组保留，不静默混算。仅在单一且身份信息完整的组中提供可直接选用的 `calibration`；仍需由调用方确认资料规模和模型设置适用。缓存命中与失败记录不用于成功回复样本范围。

## 中断后哪些会重跑

门户的回复缓存位于同一任务目录。键包含转换流程修订、整个固定技能包摘要、模型、阶段名、指令、完整请求数据和原页图片摘要；百炼还包含服务商与业务空间。改变教材原页、资料用途、输入、模型或技能包都会使受影响请求重新运行。

只有成功解析并保存的完整 JSON 回复可复用。缓存命中后仍会执行结构、来源关联与当前证据核查；成功回复不等于整个章节可以无条件跳过。单元文件与检查点用于追溯，不能替代新的语义审校要求。

提取、规划流程调度、组装、构建和实际浏览器检查仍会再执行；精确匹配的模型请求可以从缓存读取。新建上传任务、删除任务或保留期清理缓存后，不承诺复用旧调用。单个处理单元过大时应按真实小节继续拆分，不能删减正文来适应上下文。先确定资料是否发齐、范围及主次，再分章处理，能减少因条件变化引发的重复调用。
