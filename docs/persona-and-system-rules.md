# 人设文件与系统规则

## 用户编辑入口

后端用户数据目录中的 `persona.md` 是唯一角色语言入口。Windows 打包启动器使用持久的用户数据目录，而不是应用安装/解压目录。也可由受信启动配置 `FOOTBALL_ASSISTANT_PERSONA_FILE` 指定一个 `.md` 文件；HTTP 请求不能改变此路径。

首次启动后端时，若目标文件不存在且父目录已存在，从包内 `football_assistant_agent/resources/persona.md` 复制默认埃克拉文本。使用独占创建，已有文件（含无效文件）绝不覆盖。缺少自定义父目录时不递归创建，明确回退。后续每次模型请求重新读取；修改保存后下一次请求生效，无需重启。默认文件仅迁移既有人设和已确认的短句、主观判断、事实诚实风格，不新增人物设定。

- UTF-8，兼容 Windows 编辑器的 UTF-8 BOM。
- 最多 16 KiB；空文件、NUL、无效编码、超限、读取失败会使用包内默认，并保留原文件。
- 拒绝符号链接、硬链接、Windows reparse 标记；读取前核对打开文件身份。
- 不支持 include、模板执行、链接跟随或目录扫描。正文中提及其他文件只是文字，绝不读取。
- 用户文件正文会随用户主动发起的模型请求作为角色风格资料发送给已配置服务；请勿写入密钥或其他秘密。元数据接口本身不调用模型。

受认证的 `GET /v1/agent/persona` 返回固定元数据：`path/status/reason/using_default/created/max_bytes/encoding/reload`。不返回正文、Key 或模型配置。`status=fallback` 和 `reason` 明确报告回退，例如 `persona_invalid_utf8`、`persona_too_large`、`persona_file_unavailable`。`created` 仅指这次读取创建了文件。设置页应展示该状态，再通过固定的“打开人设文件/所在文件夹”动作打开后端认可的目标，不接受 renderer 任意路径。

## 三种模型路径

`modules/agent-core/src/football_assistant_agent/service.py` 的 `_chat` 统一调用 `persona.load_persona()`。普通聊天、UI 游戏建议、原生业务建议均把同一正文放入 JSON 的 `untrusted_persona` 字段；UI 建议不再另写一个覆盖人设的埃克拉开场。用户角色正文不拼接到 system prompt。历史、记忆、UI 和业务资料也不作为角色权限来源。

## 系统提示词与固定文案

- `modules/agent-core/src/football_assistant_agent/system_rules.py`：共享事实/身份/只读/授权规则，以及普通陪伴规则。角色文本不能创建权限、工具、游戏事实或数据就绪状态。
- `ui_advice.py` 的 `UI_INSTRUCTIONS`：UI 证据规则。
- `business_advice.py` 的 `BUSINESS_INSTRUCTIONS`：原生业务事实引用规则。
- `service.py`：模式组合、出站字段白名单、就绪检查、预算和固定缺数据答复；它们不会被 persona 改写。
- `managed_team_intent.py`：未确认执教球队的固定答复。
- `apps/companion/src/ui-changes.cjs`：本地主动提示，不调用模型，不受 persona 文件影响。
- `apps/companion/src/character.cjs`：桌宠展示名称/内置图片引用，与模型语言人设分离；修改 persona 不更换图片或 UI 名称。

源码中的模式规则仍是开发者维护的代码；本次只开放人设风格文件，不提供任意 system prompt/权限覆盖配置。原生和 UI 业务就绪检查、身份保护、出站白名单保持程序控制，不能被角色文字绕过。

## 打包

默认文件通过 `importlib.resources.files('football_assistant_agent')` 读取，不依赖工作目录。`pyproject.toml` 的 package-data 包含 `resources/*.md`；冻结打包也须收集该资源。用户文件位于持久目录，升级包只能更换包内默认，不覆盖用户文件。
