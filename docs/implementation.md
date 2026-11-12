# 数字教材转换网页入口

2026-10-24：用户明确要求面向无需安装 Codex 的使用者开发上传转换入口，并确认尚无服务器或模型 API，先完成可部署版本。

沿用 Python / 原生 JavaScript；同源网页与 WSGI 后台，SQLite 持久任务队列，单工作进程串行转换。托管部署使用 Gunicorn；开发预览只监听本机。模型凭证只从管理员环境读取。用户不提供密钥、不安装软件。不得将无密钥时的测试替身当作真实转换。

## 实现顺序

1. 定义接口和失败用例，复用现有 Skill，不修改原课程或安装技能。
2. 上传校验、持久队列、任务隔离、取消/恢复与定时清理。
3. 文档提取、逐页独立清单、章节映射、逐章生成、独立语义审查、结构/公式打包、真实浏览器检查及修复。
4. 完整网页；测试上传到下载链路、失败隔离、宽窄屏与离线成品。
5. 容器部署文件、配置说明、实际验收记录。公网和真实模型联调在配置可用前保持未验证。

## 统一接口（开发分工契约）

- GET /api/config → {ready, reasons:[], limits:{maxFiles,maxFileBytes,maxTotalBytes}, formats:[], retentionHours, provider, providerId:openai|bailian, accessCodeRequired}
- POST /api/jobs，JSON {title,mode:auto|textbook|slides|outline|combined,scope,consent:true,consentProvider:openai|bailian,accessCode?,files:[{name,role:textbook|teacher_slides|outline|solution|exam|auxiliary,primary:boolean,data:base64}]} → 202 {id,token,status}。无凭据返回 503；授权服务商缺失或与当前配置不同返回 409，保存资料前拒绝；绝不伪造已完成。资料类型必须逐文件可编辑。
- GET /api/jobs/:id，Authorization: Bearer <token> → {id,title,status,stage,message,createdAt,updatedAt,events:[{at,stage,message}],checks:[],downloadAvailable,expiresAt}。
- POST /api/jobs/:id/cancel；POST /api/jobs/:id/retry；DELETE /api/jobs/:id；同一 token 鉴权。
- GET /api/jobs/:id/download，Bearer 鉴权，单 HTML 附件；不通过公开文件路径获取。
- 错误统一 JSON {error:<面向用户说明>}。浏览器仅保存任务 ID/令牌；不保存书籍正文或模型密钥。令牌不在 URL。

## 后台分工接口

`portal.runner.Converter(config).run(job_dir:Path, manifest:dict, emit, cancelled) -> dict`

manifest = {id,title,mode,scope,modelProvider,files:[{id,name,role,primary,path,sha256}]}，path 为 job_dir 下的相对路径。emit(stage,message,**extras)，cancelled() -> bool。run 返回 {status:ready|needs_attention,message,checks:[{name,status,detail}],artifact:可选相对 HTML 路径}。失败可抛 ValueError；后台对外隐藏堆栈及密钥。未通过质量门禁不提供下载。modelProvider 在提交时由服务器写入；执行和重试时不匹配当前服务商则停止，请求重新上传授权。旧任务缺字段仅视为 openai，不自动改写。

config 最少提供 skill_dir, data_dir, api_key, model, max_pages, max_model_calls, browser_timeout（秒）。provider 仅支持 openai 或 bailian；后者还需 bailian_workspace_id。模型域名固定为所选服务商官方端点，百炼仅北京业务空间，不允许上传内容或环境配置指定任意代理地址。测试通过依赖注入，不提供公网 fake 模式开关。

`portal.quality.run_browser(html_path:Path, report_dir:Path, timeout:int=180) -> dict` 返回 {status:pass|fail|unverified,checks:[],screenshots:[],detail}，真实 file:// 离线浏览器。缺浏览器不能通过。

## 限制与部署

支持 PDF、TXT、MD；DOCX/PPTX 含复杂图形时要求转换 PDF 后上传，以免漏掉版式、公式或图表。单文件/总大小/页数/调用次数/任务队列均有限额；超过限额直接说明而非截断。无登录账号系统；每任务高熵令牌隔离，可选共享访问码限制公开滥用。上传资料经用户明确提交后送管理员配置的模型服务，页面说明保留与删除办法。


## schema v2 与已审内容的绑定

计划阶段返回 taskContract，生成单元返回 learningMap；先在不持久化的结构预检中核对形状与来源位置，再独立逐项审读真实原文/原页及本次用途要求。结构预检的占位记录不能导出为真实审查通过。

独立审读通过后保留单元内容快照。合并后核对正文、题目、答案、来源元数据、用途、融合记录和共同题设未在审查后改变；跨单元整卷条件必须一致，成员合并由全局审查检查。只有稳定ID映射和派生题目/答案版本确定后才生成当前绑定。后续知识修改由最终validate/build拒绝，验收说明等非知识元数据不影响绑定。

原输入文件摘要由实际字节核对，模型引用图片只能是本任务真实提取资源；图片摘要在独立审读前填入，并由最终构建再次对比文件字节。缓存记录加入转换修订号与技能文件摘要，旧v1输出不可直接升级为v2通过。

skill-lock.json锁定上游版本和精确文件摘要；本地、容器及CI使用scripts/sync_skill.py核对。服务商授权和调用总限额沿用原机制；本次维护使用明确的测试替身，未实际调用付费模型。

## 原页先读的独立抽检与章级状态

合并后先固定章节/题目 ID 和答案版本，再按章节、来源、内容类型形成可复现样本。每个样本分两次无会话历史的请求：先读取完整处理单元的真实原页及必要邻页，写出具体原文要点；全部原文观察持久化后，才向新的请求提供样本讲解、答案及这些观察，分别核对忠实性、讲解、总结和重点。请求不附生成者自评、旧审查结论、融合自述或修复建议。

原文观察、请求切片、模型返回、抽样范围和内容绑定分别保存。模型负责结论及依据，程序只记录实际请求角色和输入摘要，不补填通过。当前使用同一已配置模型的独立请求，角色 ID 不代表不同模型或人工认证。参考用途的资料不被强制融合；其总结/重点为不适用。任一样本缺证据、失败或过期都会停止下载，保留问题供修复后重试。抽检通过只覆盖所列样本，不替代逐项审校或证明全文无误。

每个样本增加一次原页读取和一次对读请求，仍计入原有任务调用限额；限额不会因本功能而重置。模型缓存绑定当前修订号、固定技能文件、原文包、图片字节及候选内容，旧结果不能越过新的输入。

浏览器入口委托固定 Skill 内的同一份运行检查，避免维护两份逐渐不同的故障测试。成功报告中的章/题范围来自实际逐一打开、宽窄屏布局和输入字段核对。章级离线记录仅绑定这些实际目标，注明实际输入代表题范围，保留对应 HTML 摘要；共享存储检查不扩展成全部题已逐一作答。已有截图未标明完整目标范围时，只保存全局可见范围的视觉审查，章级视觉状态保持未单独验证。加入这些记录后重新构建并再次检查最终 HTML 字节。网页进度也只为服务实际报告过的阶段显示完成；旧任务已经可下载，不代表它执行过后来新增的抽检阶段。
