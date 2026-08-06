# SCPHub Workspace

这是 SCPHub 的公开编排仓库。iOS/macOS App、Cloudflare Worker 和数据工具分别保存在三个
私有 Git submodule 中；本仓库只记录固定 gitlink、集成 CI、自动更新配置、公开素材和可复现
的文档包生成配方，不复制子仓库历史、抓取内容或生产数据。

有权访问三个私有仓库的开发者可以这样克隆：

```bash
gh auth setup-git
git clone --recurse-submodules https://github.com/scphub-app/scphub-workspace.git
cd scphub-workspace
git submodule update --init --recursive
```

未获私有仓库授权的访客仍可查看根仓库资料，但无法初始化 submodule。根仓库暂不授予统一
开源许可证；子仓库继续适用各自许可证，`SubscriptionProductLogos/` 中的产品标识也不因此
获得额外授权。

## 目录与职责

```text
scphub-workspace/
├── .github/                  # Dependabot、集成 CI 与安全自动合并
├── document-packs/           # 只公开生成说明和脚本，不公开生成内容
├── SubscriptionProductLogos/ # 产品素材（不额外授予许可）
├── skills/                   # 工作区辅助技能
├── tools/                    # 私有 submodule：数据与发布工具
├── scphub/                   # 私有 submodule：iOS/macOS App
└── scphub-backend/           # 私有 submodule：Cloudflare Workers
```

数据流：

```text
本地 data/scpdata-full + tools/ScpData.json
  -> tools/scp.js 更新、清洗、校验、生成 search-index.sqlite
  -> tools/site-pack-builder 生成分站 scppack
  -> CN 包和 ScpData.json 放入 iOS App Bundle
  -> 其他 15 个站点发布到 Cloudflare R2
  -> App 通过内容 API 按需下载
```

## 一体化发布工具

首次使用：

```bash
cd /Users/swift/Desktop/scphub.nosync/tools
npm ci
npm run release -- status
```

完整内容更新：

```bash
npm run release -- full
```

`full` 会依次完成环境检查、`update:all`、清洗与搜索索引重建、候选包构建、逐站版本判断、
测试、内容 API Worker 部署、R2 发布、App Bundle 资源替换和线上验证。它包含三个独立确认点：

1. 确认哪些站点需要递增版本；未变化站点复用现有版本。
2. 确认即将发生的 Worker/R2 生产写入。
3. 确认 App Bundle 中 `ScpData.json` 和 CN 包的原子替换。

工具没有跳过确认的 `--yes`。候选文件放在 `tools/.release-work/`；运行报告放在
`tools/release-reports/`。失败时保留报告和 staging 以便诊断，不会使用不完整索引继续发布。

修复索引但不更新数据或 App resources：

```bash
npm run release -- repair --default-version 1 --site zh=2
```

该命令生成精确的 15 站生产矩阵：`zh v2`，其他非 CN 站点 `v1`。它会先校验本地
manifest、文件大小、SHA-256 和远端不可变对象，再请求生产确认。

## 输入与输出位置

数据工具输入：

```text
tools/ScpData.json
data/scpdata-full/{site}/{series}.json
data/scpdata-full/{site}/SCPs/{site}-{filename}.html
data/scpdata-full/search-index.sqlite
```

builder 输出：

```text
tools/generated-site-packs/site-packs/{site}/{version}.scppack
tools/generated-site-packs/site-packs/{site}/{version}.manifest.json
tools/generated-site-packs/site-packs/{site}/{version}.missing-html.json
tools/generated-site-packs/site-packs/index.json
```

其中 `.scppack` 是发布文件，manifest 是版本、大小和哈希的权威构建记录，missing-html
只用于审计。builder 的 `index.json` **只汇总本次调用选中的站点**：执行一次单站构建会
覆盖它并使其只剩该站。因此它只是 staging 构建报告，永远不是生产发布输入。

生产索引由发布工具根据已确认的完整版本矩阵和各站点 manifest 重新生成，并强制恰好包含
全部 15 个非 CN 站点。

## iOS App 资源与运行时目录

随 App 打包的资源只有：

```text
tools/ScpData.json
  -> scphub/scphub/resources/ScpData.json

tools/generated-site-packs/site-packs/cn/{version}.scppack
  -> scphub/scphub/resources/cn.scppack
```

发布工具替换前会显示源/目标版本、大小和 SHA-256，使用同目录临时文件和原子重命名写入，
随后运行 `ContentPackIntegrationTests`。测试失败会恢复原文件。CN 始终使用 Bundle 包，不在
远端索引中，也不能在 App 内下载或删除；CN 内容变化必须递增版本并随新版 App 发布。

其他站点运行时下载到 Application Support：

```text
site-packs/index.json
site-packs/{site}.scppack
site-packs/.download-{site}-{version}.part
site-packs/.download-{site}-{version}.json
```

扩展文档包是另一套格式和目录，不要与核心 `.scppack` 混淆：

```text
packs/{siteId}/{packId}/manifest.json
packs/{siteId}/{packId}/SCPs/{siteId}-{filename}.html
```

读取正文时优先读取核心站点包，找不到时才回退到扩展包。

## Cloudflare 后端

`scphub-backend/pack-server` 提供核心站点包、扩展包和 `/admin`；
`scphub-backend/image-mirror` 代理 `*.wdfiles.com` 图片。

R2 核心对象布局：

```text
site-packs/index.json
site-packs/{siteId}/{version}.scppack
site-packs/history/{timestamp}.index.json
```

同一 `siteId + version` 是不可变资源：远端不存在时上传；哈希相同则复用；哈希不同则拒绝
并要求递增版本。发布顺序始终是包上传、远端回读校验、旧索引备份、最后替换索引。新索引
验证失败会恢复旧索引。

后端常用命令：

```bash
cd /Users/swift/Desktop/scphub.nosync/scphub-backend
npm ci
npm test
npm install --global wrangler@4.85.0
npm run dry-run
npm run deploy:pack
npm run deploy:image
```

日常 `full` 只部署内容 API Worker，不自动部署图片镜像 Worker。

## Firebase Remote Config

App 读取 `main_config` 整个 JSON，而不是单独的 Remote Config 字段。`ai_summary_template`
是必填字段；最小有效配置为：

```json
{
  "ai_summary_template": "ai-summary-v1",
  "api_base": "https://scphub-api.swiftc.cc",
  "image_mirror_base": "https://scpimg.swiftc.cc"
}
```

两个 base 都填写 origin，不带 `/api/v1`，建议不带末尾斜杠。省略 `api_base` 会使用 App
内置默认值，显式设为空字符串会禁用两类包 API。图片镜像把原 URL 改写为：

```text
{image_mirror_base}/{original-host}.wdfiles.com/{original-path}
```

## 手动测试

```bash
cd /Users/swift/Desktop/scphub.nosync/tools
npm test
swift test --disable-sandbox --package-path site-pack-builder
```

App 内容包集成测试：

```bash
xcodebuild test \
  -project /Users/swift/Desktop/scphub.nosync/scphub/scphub.xcodeproj \
  -scheme scphub \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro,OS=18.6' \
  -only-testing:scphubTests/ContentPackIntegrationTests
```

线上发布完成后，索引必须恰好包含以下 15 个站点且不含 CN：

```text
cs de en es fr it jp ko pl pt ru th ua vn zh
```

每个对象都要验证 `Content-Length`、ETag、`Accept-Ranges: bytes`、Range `206` 和完整
SHA-256。
