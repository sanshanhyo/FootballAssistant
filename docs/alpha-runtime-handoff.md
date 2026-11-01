# Alpha 本机运行与交付核对

## 当前可交付范围

- macOS arm64：已配置桥接的当前 Mac 可运行桌宠、后端、指定页面 Reader 与明确发起的建议。页面按钮不是全局 FM API。
- Windows：只验证桌宠 UI/构建路线；当前游戏采集控制为 `unsupported_platform`，不宣称端到端可用。
- `FootballAssistant.app` 只是桌宠，不包含 Python 后端、模型配置或游戏桥接安装器。它未签名/公证；不能把能本机构建当作通过新 Mac 的 Gatekeeper 验收。
- `MVP.command` 只启动/复用后端并打开桌宠，不启动第二个游戏，不安装、替换或修改游戏。

## 当前 Mac 的固定运行目录

保留同一个项目根目录，不只移动 `.app`：

```text
<项目根>/
  pyproject.toml
  uv.lock
  contracts/
  modules/{data-core,agent-core,save-adapter}/src/
  scripts/{MVP.command,run_mvp.py}
  apps/companion/dist/mac-arm64/FootballAssistant.app
  .env                         # 用户本机填写；绝不交付或上传
  local-data/                  # 启动后本机生成；绝不交付或上传
```

`uv` 是前置条件，首次运行可能需联网获取锁定依赖/Python；不是离线独立安装包。已有项目环境不需要新增依赖。Finder 启动器支持 PATH 中的 `uv` 或 `$HOME/.local/bin/uv`，缺少时明确退出，不自动安装工具。

本机配置依照现有 `.env.example` 填写模型服务地址、模型名、API key，并配置 `FOOTBALL_ASSISTANT_PRIVATE_ROOT` 为**已准备好、用户拥有的私有桥接目录**。密钥只留本机。运行目录/runtime 路径须与现有桥接一致；不要复制其他机器的 `runtime.json`。

### 引用已配置 Mac 的外部配置（不复制密钥）

候选目录不需要放 `.env`。首次从终端明确指定现有本机文件；`MVP.command` 原样透传参数：

```sh
"<候选根>/scripts/MVP.command" \
  --env-file "<原配置目录>/.env" \
  --data-dir "<原数据目录>" \
  --runtime-file "<原数据目录>/runtime.json" \
  --bridge-private-root "<已准备的私有桥接目录>"
```

`.app` 不在默认目录时再加 `--companion-path "<候选app路径>"`。可先加 `--check`，但它要求后端已经健康；不是启动命令。冷启动验收须先按原管理方式退出旧后端，再执行正常入口并确认候选代码实际启动，不误把复用当成候选后端启动。

需要真正双击而不重复键入参数时，可由用户在**候选包之外**保留一份本机启动快捷方式，只写上述路径与参数、不写密钥；没有此快捷方式或候选本机配置时，直接双击不会自动搜寻原 `.env`。

路径与优先级：CLI 路径参数优先；同名进程环境变量优先于 dotenv（这是原有约定，切换配置前须清掉冲突的 `FOOTBALL_ASSISTANT_*` 环境变量）。显式 dotenv 内及相关环境中的相对数据/runtime/bridge 路径以该文件所在目录为基准；不指定显式文件时仍以项目根为基准。`--data-dir`、`--runtime-file`、`--bridge-private-root` 的相对路径以调用工作目录为基准。Finder wrapper 会先进入候选根，直接命令行执行 `run_mvp.py` 则使用调用者目录。`--data-dir` 不覆盖另行明确配置的 runtime 文件；两者必须按原桥接路径对应指定。没有数据目录配置时，显式外部文件默认使用其同目录的 `local-data`，不偷偷改成候选目录数据库。不会迁移数据或复制配置。

显式配置缺失、不可读或过大立即报错，不搜索别的目录。后端读取该文件而非再回退候选 `.env`；Electron只收到必要系统环境和runtime路径，不继承provider/model配置、任意密钥变量或dotenv选择器。启动日志不打印配置值。已有健康后端仍复用；传入新配置不会悄悄重启它。

用户步骤：

1. 确认上述目录、构建好的 `.app`、uv 和本机配置存在。
2. 双击 `scripts/MVP.command`。连接失败/端口冲突/缺包会停止并显示原因；缺模型会警告，不能生成建议。
3. 在当前 Mac 已有、经验证的桥接游戏会话中打开目标页面。若游戏未启动，见下面的明确缺口；本入口不会偷偷启动它。
4. 右键桌宠打开设置，选择真实模式。先开赛程/战术/属性页，再点相应“读取当前页”；下一场卡片先开俱乐部概况。等 `ready`，不是只看 `applied`。
5. 观察可用/过期/未知，再向桌宠明确提问。未知球队/球员身份不因页面文本而变为已知。0% 关闭本地提示；不自动调用模型，TTS 保持关闭。

现有后端若已运行会复用，不会自动重启以加载修改后的 `.env`。配置有变时须通过原本管理后端的方式停止并重启；不杀陌生端口进程。

## 游戏桥接启动的实际缺口

`modules/game-bridge/scripts/launch_isolated.py` 是当前 Mac 的私有、单实例实验启动器：游戏路径、私有目录和 runtime 路径仍固定为该已准备环境，依赖私有 `preparation.json`、哈希验证、单独审核的 loader/CoreCLR 和游戏文件。默认只显示计划；`--launch` 才启动且拒绝已运行游戏。

它不是通用安装器，也未由 `MVP.command` 调用。因此“全退出后，新用户只双击一次就连游戏一起启动”**尚未交付**。当前 Mac 可继续使用原已验证桥接启动方式；新用户须自备正版游戏并另行完成桥接准备/路径验证。不要把私有 prepared 目录、游戏副本或运行时证据塞进发布包补此缺口。

## 最小产物与隐私边界

1. macOS arm64 `FootballAssistant.app`（压缩时保留 bundle/执行权限）及其准确 Git SHA、文件 SHA-256。
2. 匹配同一 SHA 的运行源文件包：上述 Python 模块、contracts、`pyproject.toml`、`uv.lock`、启动脚本；可含空白 `.env.example`，不可含 `.env`。
3. 已有自研 `FootballAssistant.GameBridge.dll` 如需独立交付，记录构建 SHA/哈希；不混入游戏程序集、生成互操作缓存或未经单独许可的 loader/runtime。此次不重分发私有 prepared 环境。
4. 本核对单及许可证。不是 Release 发布，也不代表新机器安装验收通过。

Electron `build.files` 正向白名单仅 `src/**/*`、`THIRD_PARTY.md`、`package.json`；另显式排除 `.env*`、`runtime.json`、local-data/local-game、数据库、日志和存档。没有 `extraResources`/`extraFiles`。这验证的是**构建规则**，不是尚未检查的 Mac 实际包内容保证。

发布前在 Mac 的实际 `.app/Contents/Resources/app.asar` 核对文件清单（使用已有 asar 工具，不下载新工具）：不得含 runtime token、provider key、`.env`、原始采样、诊断日志、存档、游戏副本/程序集或 `.git`。源文件包仅从跟踪的源码清单导出，禁止直接 zip 整个工作目录。禁止把 backend.log 或模型配置作为验收附件。检查输出只记录路径、计数、哈希及通过/失败，不打印密钥值。

## 必须保留的验收项

- 同 SHA 源码测试、包内代码和启动入口；不是旧 dist 或旧已运行进程。
- 双击启动后 backend 与桌宠读取同一个受认证 loopback runtime；错误 token/占用端口不会假装成功。
- 游戏未开/桥接缺失时清楚报告不可用，不回退模拟或编造事实；不启动第二游戏。
- 4 个固定 profile：请求、applied、fresh ready、失败；不同卡切换与迟到响应不串数据。
- 断连清旧值、恢复、15 秒过期、0%静音；下一场只三字段，身份未知。
- 跨新 capture、同语义投影的生成回复可接受；实际变化/过期/跨 session/scope 仍拒绝。
- 模型建议只在用户发送后发生；TTS关闭。Windows不勾选游戏端到端通过。
