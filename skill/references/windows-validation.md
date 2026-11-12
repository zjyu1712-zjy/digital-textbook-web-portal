# Windows 离线验收

`.github/workflows/offline-windows.yml` 在 GitHub 的 `windows-2025` 托管运行器上执行。它使用 Node 24、Python 3.12、Pillow 13.0.0 和固定的 Playwright 1.62.1 Chromium；Pillow 用于执行可选图片优化器测试。这不等同于用户安装的 Edge，也不代表 Firefox、Safari 或企业受控目录已经通过。

工作流随 main 推送运行，也可手动触发。只有工作流实际成功，且对应报告的 `platform.system` 为 `Windows`、浏览器记录包含 Windows 时，才能把该次结果列入实测矩阵。提交工作流本身不算 Windows 测试通过。

## 执行范围

- 当前技能与固定的上一发布版 1.3.0 分别检出；工作区位于安装目录外，路径含中文与空格。
- 实际执行完整 Python 单元测试、环境检测、内容校验、构建及离线资源检查；报告分别记录测试数量和跳过数量。
- Chromium 用隔离浏览器数据目录，以 `file://` 打开两章六题的自编示例并断网；执行通用运行检查、示例输入与备份、错题筛选/重做/导出/完整备份恢复及存储故障检查。
- 另用上一版构建器制作旧版文件，在同一文件入口替换为新版后核对草稿、不可变提交和题目 ID。内容变化及未绑定旧版审校不能显示为当前通过。
- 宽 1440 与 390 像素生成截图，自动检查溢出与公式渲染；截图仍需独立目视检查，报告不会自动写成视觉通过。

示例副本仅去除上一渲染器的章级浏览器证据，不修改正文，也不制造新语义审查或抽检结论。该副本只用于运行测试，不作为新的内容审校结果发布。

## 查看证据

到 GitHub Actions 的 **Windows offline acceptance** 运行详情下载 `windows-offline-evidence`。入口为 `summary.json`，其中记录系统、Python/Node、技能版本、每步耗时、浏览器版本、检查数量与实际报告路径。子目录包含各浏览器报告、所列截图及命令日志。

制品只收集显式列出的 JSON 报告、PNG 截图和日志。浏览器 profile、依赖目录、私有教材、上传文件及凭据不进入制品。示例作答全部是测试生成；浏览器报告为 `unverified`、没有检查项、出现页面错误或外部请求，都会令工作流失败。

在其他系统预演可以运行同一封装，但结果会保留真实操作系统，不能作为 Windows 证据：

```sh
python3 /技能目录/tests/windows_acceptance.py \
  --skill /技能目录 \
  --previous-skill /已核验的上一版目录 \
  --workspace '/独立目录/中文 验收'
```

可设置 `NODE_BINARY`、`PLAYWRIGHT_MODULE` 和 `BROWSER_EXECUTABLE` 指向已有工具。工作目录必须为空；封装不会覆盖已有验收记录。工作流仅声明所测托管运行器的条件，原贡献者报告中的受控 ACL 环境仍需对应机器复测。
