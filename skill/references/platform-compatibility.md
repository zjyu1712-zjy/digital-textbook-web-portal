# 跨平台安装与执行

核对日期：2026-10-25。主体使用 [Agent Skills 开放格式](https://agentskills.io/specification)：一个带 name/description 的 SKILL.md，加相对目录的脚本、参考与资源。当前使用标准 metadata 保存版本和运行需求；不设置宿主专用权限白名单。`agents/openai.yaml` 仅供 Codex 展示，其他宿主可以忽略。

## 安装目录与命令

| 环节 | 环境要求 |
| --- | --- |
| ZIP手动安装 | 不要求Node；保留整个技能目录 |
| skills CLI安装 | Node 22.20+，这是安装工具的要求 |
| 无公式构建 | Python 3.9+ |
| 含公式构建 | 另需Node；推荐已验证的Node 24，不把浏览器门槛冒充公式最低版本 |
| 浏览器验收 | Node 20+、Playwright及可用Chromium系浏览器 |
| 学习HTML | 浏览器即可，不依赖生成环境 |

安装工具启动失败时，可直接下载Release的ZIP手动安装，再运行doctor检测生成条件。

每个目录下放完整的 `digital-textbook-html/`。优先让 [官方 skills CLI](https://github.com/vercel-labs/skills/blob/main/docs/commands.md) 选择正确目录；默认项目安装，`--global` 为用户范围，`--copy` 用复制替代软链接。不要用 `--all` 修改用户没有要求的其他 AI 环境。相同名称先检查并保留已有定制，不直接覆盖。

| 宿主 | 可手动使用的项目目录 | 可手动使用的个人目录 | 发现/调用 |
| --- | --- | --- | --- |
| Codex | `.agents/skills/` | `~/.agents/skills/` | `$digital-textbook-html` 或自然语言 |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` | `/digital-textbook-html` 或自动选择 |
| Cursor Agent | `.agents/skills/` 或 `.cursor/skills/` | `~/.agents/skills/` 或 `~/.cursor/skills/` | `/` 菜单选择技能 |
| Copilot CLI | `.agents/skills/` 或 `.github/skills/` | `~/.agents/skills/` 或 `~/.copilot/skills/` | `/skills reload`、`/skills info digital-textbook-html`，再 `/digital-textbook-html` |
| Gemini CLI | `.agents/skills/` 或 `.gemini/skills/` | `~/.agents/skills/` 或 `~/.gemini/skills/` | `/skills list` 后用自然语言要求使用技能 |

目录和调用核对依据：[Claude Code](https://code.claude.com/docs/en/skills)、[Cursor](https://prod.cursor.com/docs/skills)、[Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)、[Gemini CLI](https://geminicli.com/docs/cli/using-agent-skills/)、[Codex](https://learn.chatgpt.com/docs/customization/overview#skills)。Gemini 的 `activate_skill` 是模型工具，不是用户斜杠命令。Copilot CLI 的说明不自动覆盖所有 IDE 和云端版本。

Claude Code 直接安装 Skill 不需要包装成插件。Cursor 的“从 GitHub 仓库导入”原生 UI 与本地 Skill 安装不同，可能要求其插件市场描述文件；本包使用 CLI 或目录安装，不冒充 Cursor Marketplace 插件。[Cursor 仓库导入说明](https://prod.cursor.com/docs/skills#installing-skills-from-a-repository)

## 执行能力与不足时的处理

| 能力 | 检查方式 | 不具备时 |
| --- | --- | --- |
| 技能发现与资源读取 | 宿主技能列表/激活记录，并实际读取引用文件 | 给出宿主安装步骤，不声称已调用 |
| 读写工作区、运行脚本 | doctor 实际文件写读与本地构建依赖探测 | 缺基础工具不能保证生成完整成品；列出所缺能力 |
| 提取资料、看扫描页与图表 | 实际查看用户授权原页 | 只对真实可读范围工作，模糊/缺页待核对 |
| 内容构建与语义审查 | 模型逐章对照原文及独立来源清单 | 环境检查不能代替；不虚构通过证据 |
| 浏览器与保存验证 | runtime-check 以真实 file:// 离线运行 | 标 unverified，不用服务器成功代替 |
| 视觉核查 | 宿主查看实际截图 | 没有图像查看能力则标未验证 |

这里的“模型”指当前宿主自己的模型；无需单独配置 OpenAI 或百炼 API。若宿主本身需要模型账号或费用，遵从该产品规则。纯聊天 AI、只认 MCP/OpenAPI 的插件系统、限制脚本或文件访问的沙箱，不能因有“插件”按钮就被判定完整支持；本包未提供这些产品的远程服务适配。

## 只读技能与独立工作区

技能目录存放公共资源，工作目录保存本次教材、提取、章节 JSON、检查与输出。所有脚本路径以 SKILL.md 所在目录为基准；相对输入/输出以命令执行目录为基准，因此优先传绝对路径。`--assets` 是经过授权的教材图片根目录，不是安装资源目录。

POSIX shell 示例见 SKILL.md。PowerShell 可以使用实际解释器和路径，不需要模拟 `$HOME` 或改全局变量：

```powershell
$dthSkill = 'C:\path\digital-textbook-html'
$dthWork = 'C:\path\textbook-work'
$env:PYTHONIOENCODING = 'utf-8' # 终端编码排障；脚本自身也会设置UTF-8输出
py -3 "$dthSkill\scripts\doctor.py" --workspace "$dthWork" --out "$dthWork\checks\environment.json"
py -3 "$dthSkill\scripts\pipeline.py" build "$dthWork\course.json" --inventory "$dthWork\source-inventory.json" --assets "$dthWork" --out "$dthWork\output\学习教材.html"
node "$dthSkill\tests\runtime-check.cjs" "$dthWork\output\学习教材.html" "$dthWork\checks\browser\runtime-report.json"
```

这些是对应shell的调用示例。贡献者于2026-11-11报告Windows 11 / Python 3.12 / Node 24上validate、build与inspect通过，浏览器验收因缺Playwright未执行；维护者本轮没有Windows实机复现，也未取得报告列举的原始附件。见[Issue #2](https://github.com/zjyu1712-zjy/digital-textbook-html/issues/2)。构建器明确使用UTF-8读写并配置终端输出；若宿主封装仍出现乱码，可使用上面的会话级环境设置。Python可执行名可以是python3、python或py -3；不要把多词命令塞进仅接收可执行路径的`--node`。

1.2.1环境检测逐步记录工作区创建、写入、读回和清理；Node与公式检查独立执行。工作区失败不等于Node失败；被阻断或未执行的检查不能计为通过。若清理探测文件失败，报告保留位置，供用户检查目录权限。doctor不修改ACL，也不会安装依赖。

`classify` 的输入为 JSON 对象，例如 `{"sources":[{"role":"textbook","primary":true}],"evidence":["矩阵","参数讨论"]}`。这是候选模式建议，不是自动学科认证。其余内容数据遵循 schema.md。

## 检测、打包和验收的区别

`doctor.py --workspace 工作区` 只检测所声明的运行条件，不运行 OCR、付费模型或真实浏览器，不联网安装依赖。其 buildReady 即使为 true，fullConversionVerified 仍为 false。脚本无法确认当前 AI 是否能阅读教材或图像，这些项目保持 unverified。

`package_skill.py --out 工作区/digital-textbook-html.zip` 按PACKAGE_FILES.json的精确清单打包，不打入未列出的教材、缓存或`.env`。可按RELEASE.json中的版本给输出命名。目标必须在安装目录外且不存在，避免覆盖。包内PACKAGE-MANIFEST.json记录文件SHA-256，用于完整性核对，不是签名或教学质量证书。

安装成功、宿主识别、实际模型调用、内容核查与浏览器通过分别记录。没有安装某 AI 或登录其模型，就不能宣称已经在该 AI 中端到端验证；当前实测见 release-1.1.0.md。
