# 中国大陆小范围试用上线

目标预算：每月 200 元以内。建议先将服务器与域名摊销控制在约 60 元/月以内，模型试用预留 100 元，其余留作缓冲。这是规划额度，不是服务商报价或程序保证的消费上限；整本教材需要逐页识别、生成和核查，不能承诺无限次转换。服务器的实际内存需求和单本费用要用真实样本测量后再决定开放范围。

## 先由管理者完成的注册

1. [注册阿里云账号](https://account.aliyun.com/)，完成实名认证。服务器、域名与百炼可使用同一账号管理。先注册，不必立即购买。
2. 打开[阿里云百炼控制台](https://bailian.console.aliyun.com/)，按页面要求自行阅读协议并开通。选择**北京**业务空间，取得该空间的 ID，创建模型调用 API Key。这里使用按量模型 API，不是 Coding Plan、专属实例或模型训练。密钥只写入自己服务器上的 `.env`，不要发送到聊天或提交到 GitHub。
3. 在实际购买前核对轻量应用服务器报价：建议先看中国内地地域、2 核 4 GB、40 GB 或以上磁盘、Ubuntu 22.04/24.04 或 Docker 镜像。当前 Compose 给转换服务最多 3 GB 内存，2 GB 主机不能按此配置直接套用。套餐要满足预算及备案资格；若报价超标，先重新比较方案，不直接购买高价配置。
4. 注册并实名认证域名。中国内地服务器通过域名公开提供网站服务，需要按要求完成 ICP 备案；备案资格取决于服务器套餐及购买时长，应以购买页与备案控制台核验结果为准。不要为了跳过备案将正式服务直接公开到 IP 地址。

账号注册、实名、支付与备案材料应由管理者本人完成。网站公开提供生成服务前，还需向接入商确认自己的服务形态所需的生成式 AI 等备案或登记手续；购买模型 API 不代表网站运营所需手续自动完成。

## 服务器配置

服务器就绪后，用管理者自己的 SSH 账号登录，安装官方 Docker Engine 与 Compose 插件。防火墙开放 80/443，管理端口只向必要来源开放。将域名解析到服务器公网地址，在备案及公开访问条件满足后部署：

```sh
git clone https://github.com/zjyu1712-zjy/digital-textbook-web-portal.git
cd digital-textbook-web-portal
cp .env.bailian.example .env
chmod 600 .env
```

用服务器编辑器填写 `.env`：

| 配置 | 填什么 |
| --- | --- |
| `PORTAL_DOMAIN` | 自己实际使用的域名，例如 `books.example.com`，不带协议或路径 |
| `PORTAL_PUBLIC_ORIGIN` | 对应 HTTPS 地址，例如 `https://books.example.com` |
| `DASHSCOPE_WORKSPACE_ID` | 北京业务空间 ID，只填 ID，不填网址 |
| `DASHSCOPE_API_KEY` | 该业务空间的 API Key，只在服务器保存 |
| `DASHSCOPE_MODEL` | 示例为 `qwen3-vl-plus`，需确认账号可调用并支持图片及非思考 JSON mode |
| `PORTAL_ACCESS_CODE` | 自设的共享试用访问码，与模型密钥分开 |

服务只请求固定的百炼北京官方域名：`https://{业务空间ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions`。不接受任意转发地址，也不会退回使用另一家服务的密钥。网页授权提示及成品核查说明会显示“阿里云百炼”。上传、排队执行和重试均核对用户授权的服务商；切换服务商后旧任务不会自动转发，需重新上传并授权。不要把完整教材写入镜像或仓库。

```sh
docker compose up --build -d
docker compose exec portal python scripts/preflight.py --browser
```

Caddy 自动管理 HTTPS；不要额外公开后台 8000 端口。持久卷保存任务与检查点。保留默认一个后台进程，避免并发进程争用队列。不要执行带 `-v` 的 `docker compose down`，那会删除数据卷。

内地服务器能否直接拉取 Docker Hub、PyPI、npm 和 GitHub 资源，取决于实际网络。如果构建下载失败，应定位下载环节，再使用服务商认可的镜像或离线搬运已验证镜像；不要禁用 TLS 验证或运行来源不明的安装脚本。

## 上线验收与费用控制

预检实际检查本机依赖、持久目录和 `file://` 浏览器运行，但**不发送付费模型请求**。填了密钥后预检通过，只代表可以开始首次真实试用。

先在 HTTPS 页面上传仓库自编的 `skill/tests/fixtures/general-source.txt`，再用自己有权处理的 10–20 页代表性 PDF（含公式、图表、练习）实测。必须确认：

- 上传告知的服务商正确；未授权、错误访问码及过大输入会拒绝。
- 真实模型完成转换；原内容、所有小问、答案标签与覆盖范围无遗漏，失败不能下载冒充完成的成品。
- 下载的单文件 HTML 能直接打开，断网可读、可作答、可备份；实际保存测试有通过记录。
- 重启后任务能恢复或明确显示“中断后可重试”；任务主动删除与到期清理有效。
- 在百炼账单查看本次真实调用量和费用，结合主机内存占用决定后续范围。

示例配置将队列设为 2、单任务模型请求次数设为 80（含重试），并保留 24 小时。达到请求上限会明确停止，不通过删章降低标准。它不是全站月度人民币限额；重复任务和重试仍可能继续产生费用。应设置服务商支持的消费提醒，初期保留共享访问码，接近预算时停止新任务。若要完全匿名开放，需先实测并补足全站费用和滥用控制，不能把目前的小范围部署视为无限量公共服务。

现有工程不记录或保证服务商零保留。百炼处理上传内容时适用其数据规则；本地删除不会撤销既有服务商处理。不要把真实教材放进公开 CI。仓库容器检查只使用自编样本、测试替身与断网浏览器，不验证真实 API 权限或学术结果。

## 官方核对入口

- [百炼开通、API Key 与业务空间](https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen)
- [OpenAI 兼容的 Chat Completions 接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [视觉输入](https://help.aliyun.com/zh/model-studio/vision/)、[结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
- [轻量应用服务器产品](https://www.aliyun.com/product/swas)、[域名与备案说明](https://help.aliyun.com/zh/simple-application-server/user-guide/manage-domain-names/)

接口与说明核对日期：2026-10-24。模型价格、套餐、资格和运营手续以服务商当前页面及实际审核为准。
