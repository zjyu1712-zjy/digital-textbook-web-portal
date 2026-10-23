# 数字教材 · 网页转换入口

使用者打开网站，上传教材（或教材与课件、提纲、解析、真题），选择资料主次，等待处理和检查，下载一个可离线学习的 HTML。无需安装 Codex、配置模型密钥或启动本机服务器。

**当前交付为可部署工程，不是已经上线的公共网站。** 当前开发环境没有模型 API 和公网服务器。网页交互、真实打包、离线浏览器与故障门禁经过测试；付费模型的完整转换和容器部署尚未实测，详见 `ACCEPTANCE.md`。模型测试替身只在 `tests/`，生产服务没有假转换开关。

本仓库包含网页、任务后台、转换流程、检查工具与 Docker Compose 部署配置。仅需在 Codex 中使用 Skill 时，可使用独立的 [digital-textbook-html 仓库](https://github.com/zjyu1712-zjy/digital-textbook-html)。本工程随附 `skill/`，部署时不需要安装 Codex，也不需要从另一仓库临时下载组件。

中国大陆、月预算 200 元以内的试用部署，先看 [国内上线步骤](docs/mainland-deployment.md)：阿里云账号、百炼北京模型 API、轻量服务器与域名备案。对应配置为 `.env.bailian.example`；无需使用者安装 Codex。

下载工程：

```sh
git clone https://github.com/zjyu1712-zjy/digital-textbook-web-portal.git
cd digital-textbook-web-portal
cp .env.example .env
```

也可以在 GitHub 仓库页面选择 **Code → Download ZIP** 后解压。填写 `.env` 后，按照下面的步骤部署；将代码上传到 GitHub 本身不会启动转换服务，GitHub Pages 也不能运行本工程的后台。

## 网站管理者上线

准备一台可访问模型服务的 Linux 服务器、Docker Compose、指向服务器的域名，以及模型 API 凭据。支持阿里云百炼北京业务空间（视觉输入、非思考 JSON mode）或 OpenAI Responses（视觉输入、JSON mode）。模型调用与服务器费用由管理者承担；ChatGPT/Codex 登录状态不会自动变成此网站的 API 凭据。建议先限量试用，通过短教材实际转换再开放。

1. 在服务器下载本工程。百炼复制 `.env.bailian.example` 为 `.env`，填写业务空间、模型与 API Key；OpenAI 使用 `.env.example`。两者都要填写 `PORTAL_DOMAIN` 及一致的 HTTPS `PORTAL_PUBLIC_ORIGIN`。不要把密钥发到聊天、前端代码或分享包里。
2. 可设置 `PORTAL_ACCESS_CODE`，先让使用者凭共享访问码进入转换。访问码不是模型密钥，也不是账号系统。未设置访问码时，知道网站地址的人均可提交并消耗模型费用；仍有任务、文件、调用和存储限额。
3. 确认域名已经解析，80/443 端口可达，然后在该目录执行：

   ```sh
   docker compose up --build -d
   docker compose exec portal python scripts/preflight.py --browser
   ```

   Caddy 提供 HTTPS。后台不直接公开 8000 端口。必须保持 Gunicorn **一个进程**，线程可以处理上传与查询；另有一个串行后台工作线程。SQLite 与任务文件使用持久卷。多副本、跨机器队列未实现。

   默认资料总量 60 MiB，上传编码后更大，代理限额设为 96 MiB。若调整 `PORTAL_MAX_TOTAL_BYTES`，同步调整 `Caddyfile` 的 `max_size`，至少预留原文件总量的 4/3 和请求元数据空间。

4. 打开你的 HTTPS 地址，先上传 `skill/tests/fixtures/general-source.txt` 自编短样本。它将通过真实模型处理，检查后下载 HTML。核查内容、答案标签和保存恢复，再用代表性 PDF（含扫描页、公式、图表和练习）验证。预检不调用模型，不等于 API 权限和真实转换已验证。
5. 分享网站地址；普通使用者只需要网页。下载后离线阅读、作答和备份，不依赖网站继续运行。

不要未经备份执行 `docker compose down -v`，这会删除任务数据卷。普通 `down`/`up` 保留卷；运行中任务重启后标为已中断，使用者点“继续/重试”，已通过的模型调用按输入、规则、模型和图片摘要从检查点复用。

## 本机查看网页

无需填写密钥即可看上传界面，但提交会明确禁用。

```sh
python3 -m portal --port 8000
```

打开 `http://127.0.0.1:8000`。此开发入口只监听本机，不能把它当作公网发布方式。手动运行转换时，Python 需 3.12 或更新版，安装 `requirements.txt`、Node/Playwright 和可用 Chromium 浏览器；可设置 `NODE_BINARY`、`PLAYWRIGHT_MODULE`、`BROWSER_EXECUTABLE`。容器已声明这些依赖，但当前机器没有 Docker，容器构建仍需上线时实测。

## 转换与检查

- 直接加载随包 `skill/` 的质量要求、个人学习偏好、资料模式、学科细则和数据契约，调用原 Python 构建器、公式检查器与学习组件。没有为五门课重写五套网页。
- PDF 逐页提取文字并渲染原页供模型核查。扫描 PDF 可走视觉识别；模糊、损坏、缺页或无法确认的资料停为待核对。TXT/MD 必须 UTF-8。简单 DOCX/PPTX 可读取；有图片、公式、图表、表格、备注、脚注或复杂绘图时，明确要求从原应用导出**包含相关内容**的 PDF，不能静默丢弃。PPT 备注应使用备注页导出。
- 在写课程之前独立生成逐页来源清单；按真实章节组织，长章按小节处理。讲解与答案由模型构建，另一次请求对照原页做语义核查，结构计数不冒充学术正确。原答案/教师答案/未知参考/AI答案分别标记。
- 每处理单元至多八个原页，超大单元或上下文上限明确阻塞，不截断、不把后续章压成摘要。极长目录规划或跨章索引仍可能达到处理上限，此时保留检查点并报告，不保证任意长度教材都可一次处理。
- 单元结构/公式或语义错误至多自动修复三轮，失败保留问题。来源缺失、全局映射冲突、公共组件或视觉失败不会凭猜测发布；需要补资料或维护后重试。原页、用户输入、修复记录和各阶段结果在当前任务目录保存，最终只下载一个 HTML。
- 打包后实际以 `file://` 断网打开，检查真实章节、题型、默认隐藏答案、三次提交、草稿/附件恢复、备份重复导入与冲突、记录隔离、版本追溯及宽窄屏。截图另送模型审查可见区域。验收说明写入 HTML 后再次测试最终文件并记录 SHA-256。
- 同一主资料、相同范围和模式使用稳定教材命名空间，内容与答案版本由内容摘要确定。当前网页是新教材转换入口，尚未提供旧系统 HTML 或更换教材版本的迁移入口；不要直接用新文件覆盖已有学习系统并期待旧记录自动迁移。

## 数据与边界

模型密钥只保留在服务器环境中，浏览器与生成 HTML 不包含密钥。上传时页面显示当前服务商（阿里云百炼或 OpenAI），由使用者勾选同意；服务只访问所选服务商的固定官方地址，不接受自定义转发地址，不跟随模型 API 重定向。百炼配置不会读取 OpenAI 密钥，反向亦然。OpenAI 请求使用 `store:false`，仅关闭 Responses 应用状态保存；百炼不使用该参数。两者均不能据此宣称服务商无日志或零保留，应核对各自数据规则。

任务访问凭据随机生成，服务端只存凭据哈希；每个任务隔离。网页将任务编号和凭据存入当前浏览器，刷新或重开可恢复。清理浏览器或丢失这些凭据后，当前没有账号找回机制。凭据不出现在下载 URL，可见范围内的使用者应保护自己的浏览器。

默认自提交起保留 24 小时，定时清理；可主动删除，进行中的调用会在安全检查点停止后清理。本服务删除不等于撤销服务商既有处理。模型调用/服务器宕机期间不能承诺永久运行或即时停止。共享访问码、HTTPS、任务限额用于小范围部署；大规模公开运营前还需要实际压力测试、速率治理、费用预算与运维。

## 测试与维护

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/runtime-check.cjs /absolute/path/to/generated.html /absolute/path/to/report.json
```

网页端到端测试说明见 `tests/portal.e2e.cjs`，使用固定自编来源、依赖注入和临时隔离目录，明确不算真实模型联调。`tests/serve_ui_fixture.py` 不会打进生产容器。

用户偏好位于 `skill/references/preferences.md`；质量策略位于 `skill/references/quality.md`，页面样式位于 `static/`，成品样式位于 `skill/assets/style.css`。调整偏好不要修改记录存储或稳定 ID。网页副本包含草稿缓存修复 `1.0.0-web.1`，来源与失败复现见 `evidence/quality/repair-record.json`。原始课程目录、原 Skill 与安装版不改动。

`ACCEPTANCE.md` 记录开发阶段的验收范围，`docs/publication-check.md` 记录本公开副本的复测。原始浏览器运行目录、截图和完整日志保留在本地开发工作区，未随仓库发布；修复摘要中的报告路径仅用于追溯，公开仓库提供可重新运行的测试代码。`.env`、任务数据库、上传教材、用户作答、依赖缓存均不属于发布内容。

可在 GitHub Actions 手动运行 **Container check (no model calls)**，构建实际 Dockerfile 并在断网容器检查两套测试、持久卷、Linux Chromium 和 HTTP 服务。该流程不读取真实密钥、不调用模型、不部署网站。

百炼 API 实现依据：[首次调用与北京业务空间](https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen)、[兼容接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)、[视觉输入](https://help.aliyun.com/zh/model-studio/vision/)、[JSON 模式](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。

OpenAI API 实现依据：[Responses JSON 模式](https://developers.openai.com/api/docs/guides/structured-outputs#json-mode)、[视觉输入](https://developers.openai.com/api/docs/guides/images-vision#analyze-images)、[数据控制](https://developers.openai.com/api/docs/guides/your-data)。
