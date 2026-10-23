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

- GET /api/config → {ready, reasons:[], limits:{maxFiles,maxFileBytes,maxTotalBytes}, formats:[], retentionHours, provider, accessCodeRequired}
- POST /api/jobs，JSON {title,mode:auto|textbook|slides|outline|combined,scope,consent:true,accessCode?,files:[{name,role:textbook|teacher_slides|outline|solution|exam|auxiliary,primary:boolean,data:base64}]} → 202 {id,token,status}。无凭据返回 503；绝不伪造已完成。资料类型必须逐文件可编辑。
- GET /api/jobs/:id，Authorization: Bearer <token> → {id,title,status,stage,message,createdAt,updatedAt,events:[{at,stage,message}],checks:[],downloadAvailable,expiresAt}。
- POST /api/jobs/:id/cancel；POST /api/jobs/:id/retry；DELETE /api/jobs/:id；同一 token 鉴权。
- GET /api/jobs/:id/download，Bearer 鉴权，单 HTML 附件；不通过公开文件路径获取。
- 错误统一 JSON {error:<面向用户说明>}。浏览器仅保存任务 ID/令牌；不保存书籍正文或模型密钥。令牌不在 URL。

## 后台分工接口

`portal.runner.Converter(config).run(job_dir:Path, manifest:dict, emit, cancelled) -> dict`

manifest = {id,title,mode,scope,files:[{id,name,role,primary,path,sha256}]}，path 为 job_dir 下的相对路径。emit(stage,message,**extras)，cancelled() -> bool。run 返回 {status:ready|needs_attention,message,checks:[{name,status,detail}],artifact:可选相对 HTML 路径}。失败可抛 ValueError；后台对外隐藏堆栈及密钥。未通过质量门禁不提供下载。

config 最少提供 skill_dir, data_dir, api_key, model, max_pages, max_model_calls, browser_timeout（秒）。模型域名固定为官方 OpenAI，不允许上传内容指定网络地址。测试通过依赖注入，不提供公网 fake 模式开关。

`portal.quality.run_browser(html_path:Path, report_dir:Path, timeout:int=180) -> dict` 返回 {status:pass|fail|unverified,checks:[],screenshots:[],detail}，真实 file:// 离线浏览器。缺浏览器不能通过。

## 限制与部署

支持 PDF、TXT、MD；DOCX/PPTX 含复杂图形时要求转换 PDF 后上传，以免漏掉版式、公式或图表。单文件/总大小/页数/调用次数/任务队列均有限额；超过限额直接说明而非截断。无登录账号系统；每任务高熵令牌隔离，可选共享访问码限制公开滥用。上传资料经用户明确提交后送管理员配置的模型服务，页面说明保留与删除办法。
