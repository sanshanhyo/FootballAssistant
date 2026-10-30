# Save Adapter MVP

已有可重复用户入口，原存档只读，使用独立副本进行解析和本机导入。

```sh
uv run --frozen --extra save football-assistant-import-save "$HOME/Library/Application Support/Sports Interactive/Football Manager 27/games/example.fm"
```

命令依次做稳定性检查、复制到受限 `local-data/save-snapshots`、检查原件与副本摘要及原件状态、窄格式解析、鉴权 POST 到本机 Data Core。不会调用模型，不启动 watcher，不修改原件。退出 0 表示成功导入，2 表示不支持的格式/构建或没有观测，1 表示文件、稳定性、服务等失败。

固定 `fmsave==0.7.0`（MIT）的高层 `Save` API 仍只支持 FM26，对真实 FM27 明确 unsupported；没有绕过其版本检查。独立的 `summary.py` 只复用其 FMF/zstd 容器 reader，按签名、schema31、build `27.0.0+2486695` 和完整长度前缀 grammar 读取两个实验性摘要字段。压缩 summary 最大 2 MiB、解压最大 1 MiB，严格检查长度、UTF-8 和日历日期；未知 schema/build/格式不输出事实。

仅输出 `save_summary.club_label` 原文标签与 `game_date`，不输出球队实体、ID、球员阵容、经理信息或未经验证的时刻。首份真实样本已与 FM27 屏幕交叉核对；不同 SHA 的同构建 backup 副本也通过结构对照。新保存可以解析，但只标格式检查及初始样本 UI 证据，不谎称逐次 UI 核对。当前 snapshot SHA 与 UI 证据 sample SHA 单独记录，只有相同时才使用 exact UI 方法。

`probe` / `read_snapshot` 是高层 fmsave 兼容性探测；`read_summary_snapshot` 是独立两字段窄适配器。`football-assistant-save-summary --confirmed-copy ... --output ...` 可单独生成信封，`football-assistant-import-save` 则完成源文件到入库的显式流程。所有数据仍是 save snapshot，不是实时采集。详见 [Backend API](../../docs/backend-api.md)。
