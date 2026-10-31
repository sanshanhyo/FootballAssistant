<p align="center">
  <img src="assets/logo.png" width="160" alt="FootballAssistant Logo">
</p>

<h1 align="center">Football Assistant</h1>

<p align="center">
  一个面向 FM27 的非官方 AI 桌宠助教，陪你讨论球员、转会、战术与赛程。
</p>

<p align="center">
  <a href="https://github.com/sanshanhyo/FootballAssistant/releases"><img src="https://img.shields.io/github/v/release/sanshanhyo/FootballAssistant?include_prereleases&style=flat&logo=github&label=Release" alt="GitHub Release（含预发布版本）"></a>
  <a href="https://space.bilibili.com/433833099"><img src="https://img.shields.io/badge/Bilibili-散山肆水HyO-00A1D6?style=flat&logo=bilibili&logoColor=white" alt="Bilibili"></a>
  <a href="https://t.me/SanshanHyo"><img src="https://img.shields.io/badge/Telegram-@SanshanHyo-26A5E4?style=flat&logo=telegram&logoColor=white" alt="Telegram"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-blue?style=flat&logo=gnu" alt="GNU GPL v3"></a>
</p>

<!-- 待补充 FootballAssistant 的实际界面截图。 -->

## 下载

请前往 [Releases](https://github.com/sanshanhyo/FootballAssistant/releases) 下载对应平台的 Alpha 版本。尚未发布的测试构建可在 [GitHub Actions](https://github.com/sanshanhyo/FootballAssistant/actions/workflows/desktop.yml) 中选择 `integration/alpha-reader-ui` 分支的成功构建下载（下载 artifact 可能需要登录 GitHub）。

- 首次启动会自动生成配置文件，可在设置中填写模型服务地址、模型名称和 API Key。

**⚠️⚠️目前 Football Assistant 处于 Alpha 测试阶段，各项功能仍不稳定，同时正在快速更新中，请做好存档备份⚠️⚠️**

若遇到 BUG，可以在 [Issues](https://github.com/sanshanhyo/FootballAssistant/issues) 中或加入 QQ 群反馈。如果你有好点子，也欢迎提出；能提供实现的 Fork 或提交 PR 就更好了！

## 功能

- [X] 允许玩家在游戏中与桌宠进行文字聊天。
- [X] 第三方模型 API 接入，可在设置中配置。
- [X] 读取已支持页面中的球员属性、战术摘要、赛程及下一场比赛信息。
- [X] 根据已读取的数据回复玩家，并对已支持的数据变化提供基础主动提示。
- [X] 分段短句回复，可编辑 `persona.md` 调整人设。

当前读取依赖游戏中已打开的受支持页面，可在设置中点击“读取当前页”，还不是覆盖整个游戏的后台数据接口。完整球员身份、转会报价与合同、预算、伤病、阵容角色与职责等数据仍待完善；转会、轮换等建议会结合已有信息或玩家补充，不代表已经读到了这些数据。当前仅内置艾克拉，TTS 暂未启用。

## Road Map

- [ ] Alpha 0.0.2 - 角色库，角色切换，实装 TTS 系统，修改界面；
- [ ] Alpha - 扩充读取覆盖与建议质量，完善滚动更新、配置迁移和故障恢复，加入不依赖新游戏接口的轻量娱乐互动；
- [ ] Beta - 接入 FMAPI，稳定读取接口；

**我们非常需要你的帮助，无论是提出功能、反馈 BUG，还是提交 PR，这对我们都十分重要。**

## 致谢

FootballAssistant 的实现离不开以下优秀的开源项目与社区资源：

- [dsh-pet](https://github.com/PC2005-cloud/dsh-pet)：部分桌宠多屏窗口与拖拽处理代码。
- [UnityDoorstop](https://github.com/NeighTools/UnityDoorstop) 与 [.NET/CoreCLR](https://github.com/dotnet/runtime)：游戏桥接加载与运行基础。
- [fm26-player-export-macos](https://github.com/DadMych/fm26-player-export-macos)：macOS 兼容与加载方案参考。
- [fmsave](https://github.com/rhiever/fmsave)：可选的有限存档解析适配。
- [BepInEx](https://github.com/BepInEx/BepInEx) 与 [Dobby](https://github.com/BepInEx/Dobby)：早期兼容实验及可选原生观察模块。
- 851 GBai Marker 字体及其作者与贡献者：具体来源和许可见项目内的第三方声明。

也感谢所有直接或间接参与上述项目的开发者与贡献者。第三方代码与资源分别遵循其各自许可。

## 免责声明

FootballAssistant 是独立开发的非官方辅助项目，与 Football Manager 27 的开发商、发行商不存在官方隶属、合作或背书关系；游戏名称、商标及相关内容的权利归各自权利人所有。本项目不提供游戏本体、破解或授权绕过功能，请使用合法取得的游戏，并遵守适用的游戏许可协议及法律法规。

本项目基于 [GNU General Public License v3.0](LICENSE) 开源。第三方代码与资源分别遵循其各自许可。
