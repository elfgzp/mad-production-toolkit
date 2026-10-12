# MAD Production Toolkit

**简体中文** | [English](README.en.md)

一套用于音乐视频与翻奏 MAD 制作的 Codex Skills。它把已获授权的本地素材串成可追溯的流程：素材整理、镜头规划、分轨对齐与混音、歌词时间轴、视频合成，以及交付检查和打包。

**画面和声音风格由每个项目决定。** 字体、字号、颜色、位置、标题文案、淡入淡出、分屏布局、均衡、音量、声像和效果均可配置。仓库中的 JSON 是虚构示例，不代表固定风格或预设混音。

## 技能

| Skill | 用途 |
| --- | --- |
| `mad-source-assets` | 记录素材来源、权利状态、媒体信息和哈希，并复制到项目目录。 |
| `mad-plan-shots` | 根据节拍与段落规划镜头，生成精确帧数的动画画面和剪辑清单。 |
| `mad-align-stems` | 对照参考分轨检查乐句，对确认有偏移的片段做局部时间修正。 |
| `mad-time-lyrics` | 校对歌词覆盖范围，导出字幕，生成可配置的双语动态歌词。 |
| `mad-mix-audio` | 对齐后并轨混音，设置自动化、均衡、声像、贝斯压缩及效果层。 |
| `mad-edit-video` | 合成并缓存乐手与动画画面，制作标题、署名、歌词叠层和音频修订版。 |
| `mad-deliver-project` | 检查成片，整理项目清单，校验视频与音频压缩包。 |

使用脚本前，先阅读 [`plugins/mad-production-toolkit/skills`](plugins/mad-production-toolkit/skills) 中对应技能的 `SKILL.md`。[完整流程说明](docs/workflow.md)涵盖各阶段交接、可选的贝斯处理、版本修订和人工复核要点。发现时间、混音或画面问题时，可以返回相应阶段修改；项目素材与配置应保存在自己的项目目录中。

## 在 Codex 中安装

```bash
codex plugin marketplace add elfgzp/mad-production-toolkit
codex plugin add mad-production-toolkit@mad-production-toolkit
```

此 GitHub 仓库可作为 Codex 插件市场源。进入 OpenAI 公共插件目录需要单独提交和审核。

## 运行环境

- Python 3.10 或更新版本；音频分析和文字渲染需要 `numpy`、`Pillow`。
- `PATH` 中可用的 FFmpeg 和 FFprobe，并支持 H.264、AAC、FLAC、ProRes 编码。
- 你有权为预期用途剪辑、展示和分发的本地素材。本仓库不包含实际视频、录音、歌词、翻译、Logo、字体、NAM 模型或脉冲响应文件。

用 `python3 -m pip install -r requirements.txt` 安装 Python 依赖。各技能的 `SKILL.md` 说明了命令和配置格式。脚本只处理明确指定的本地路径，不调用托管媒体服务。

## 开发与验证

```bash
python3 scripts/validate_all.py
```

测试会在临时目录生成短音频和视频，无需项目素材。验证脚本检查全部技能、两份插件清单及端到端流程。发布前还应检查 Git 暂存文件，避免提交私人路径、凭据和第三方媒体。

## 许可与数据

工具包的原创代码和文档采用 MIT 许可；该许可不覆盖你提供的媒体。数据处理说明见 [PRIVACY.md](PRIVACY.md)，贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。
