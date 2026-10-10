<!-- About 简介（推送后填写到仓库 About 栏）：
口播剪辑专家：一句话把口播素材剪成爆款短视频 ｜ 一键安装：/plugin marketplace add lhg-plugs/lhg-video-edit
-->
<!-- topics（推送后打）：claude-code, claude-plugin, agent-skills, video-editing, ffmpeg, subtitle -->

# lhg-video-edit：口播剪辑专家

> **一句话介绍**：一句话把口播素材剪成爆款短视频——转录清洗、口头禅删除 EDL、ffmpeg 渲染、字幕封面、31 条确定性规则自检全流程；另带口播脚本子命令（钩子/分镜/提词器），"说什么"和"怎么剪"一次配齐。
>
> **一键安装**：在 Claude Code 里运行
> ```
> /plugin marketplace add lhg-plugs/lhg-video-edit
> /plugin install lhg-video-edit@lhg-plugs
> ```

## 它是什么

`lhg-video-edit` 是一个 Claude Code 插件（plugin 为主、skill 为辅），专为"素人口播博主"设计：

- **3 个命令**（小白入口）：`video-edit` 一句话剪口播（转录→EDL→渲染→字幕/封面→自检），`video-script` 写口播脚本（钩子→分镜→提词器），`video-audit` 成片自检
- **4 个平台中立 skill**（方法论，可移植到豆包/Workbuddy 等 agent 平台）：转录与文本清洗、口播脚本、EDL 剪辑流水线、成片自检
- **3 个专家 agent**：剪辑师、脚本师、独立质检员
- **1 个硬门 hook**：渲染 final.mp4 前自动校验 EDL 有效性（可一键豁免，不骚扰）
- **31 条确定性自查规则**：字幕错别字、时长、封面尺寸、音量归一、违禁词，纯 Python、零第三方依赖，5 秒出结果

工作流：`video-script`（说什么）→ `video-edit`（怎么剪）→ `video-audit`（查一遍），也可以只用其中一段。

## 3 个命令用法

| 命令 | 作用 | 示例 |
|---|---|---|
| `/lhg-video-edit:video-edit` | 一句话剪口播：素材→转录→EDL→渲染→字幕/封面→自检 | `/lhg-video-edit:video-edit ./raw.mp4 --target 60` |
| `/lhg-video-edit:video-script` | 主题→3 种钩子（用户选）→分镜脚本→口语化检测→提词器 | `/lhg-video-edit:video-script "新手定投" --len 60` |
| `/lhg-video-edit:video-audit` | 成片自检（脚本 + 人工评审清单） | `/lhg-video-edit:video-audit ./delivery/` |

## 自查说明

自查 = 确定性脚本（机器）+ 人工评审清单（人）：

1. 先跑 `scripts/audit/video_audit.py`（31 条规则：字幕 8、EDL 8、时长 2、封面 5、音频 4、合规 4），零 LLM 成本；
2. 发现分三级：**blocker**（必须修，渲染前 hook 会拦截坏 EDL）、**warning**（修或写豁免理由）、**nit**（顺手修）；
3. 再按 `lhg-ve-audit` skill 的评审清单过一遍脚本抓不到的（前 3 秒钩子、封面点击欲、音乐版权、题材合规）。

blocker 清零才算做完；为清零改规则算作弊，不许。

## 目录结构

```
lhg-video-edit/
├── .claude-plugin/          # plugin.json（插件清单）+ marketplace.json（本仓即市场）
├── commands/                # 3 个命令：video-edit / video-script / video-audit
├── skills/                  # 4 个平台中立 skill（转录清洗/口播脚本/EDL 流水线/成片自检）
├── agents/                  # 3 个专家 agent（editor / scripter / qa-reviewer）
├── hooks/                   # 1 个硬门（渲染前 EDL 校验）+ 豁免说明
├── scripts/audit/           # 31 条确定性自查规则（零第三方依赖）
├── fixtures/                # 冒烟测试用例（坏/好对照）
├── smoke_test.py            # 一键冒烟测试
├── ATTRIBUTION.md           # 灵感来源与许可声明
└── LICENSE                  # MIT
```

## 什么时候用 / 什么时候不用（FAQ）

**什么时候用：**

- 你拍了口播素材，但一想到剪辑（卡点、字幕、删口头禅）就头大时 → 用 `/lhg-video-edit:video-edit`，一句话出成片
- 你想拍口播但不知道"说什么"时 → 先用 `/lhg-video-edit:video-script` 定钩子写脚本，再拍再剪
- 你要发布前怕翻车（错别字、违禁词、封面尺寸错）时 → 跑 `/lhg-video-edit:video-audit`
- 你想给团队/工作室立一套"剪辑必须过自检"的纪律时 → 它的 hook 硬门与审计脚本开箱即用

**什么时候不用：**

- 你剪的是剧情/混剪/卡点舞蹈等强视觉创意类视频 → 本插件是"口播"专家，创意剪辑请找更通用的剪辑 skill
- 你的素材是英文/方言且口音很重 → 转录错误率会上升，先人工校对转录稿再进流水线（见 lhg-ve-transcript 第 6.5 节）

**风险点诚实说明：**

- **转录成本**：云端词级转录按量计费，动手前插件会先报价；私密素材请走本地免费路线（faster-whisper），把原声上传到第三方前请三思
- **渲染耗时**：10 分钟以上长素材渲染按比例耗时，动手前会先告诉你预计时长；想快就用代理剪辑/降低预览分辨率
- **版权音乐**：BGM 三选一——自制 / 已购版权 / 平台免费曲库；"网上下载的热歌"不算来源，自检脚本会标 warning，发布前请确认授权
- **违禁词库是启发式**：31 条规则里的极限词表是自建常用表，会持续扩充但不可能穷尽；误报时按"误报处理"流程豁免，不要直接删规则

## lhg-plugs 插件矩阵

| 插件 | 一句话 | 安装 |
|---|---|---|
| [lhg-video-edit](https://github.com/lhg-plugs/lhg-video-edit) | 一句话把口播素材剪成爆款短视频（+口播脚本子命令） | `/plugin install lhg-video-edit@lhg-plugs` |
| [lhg-fullstack](https://github.com/lhg-plugs/lhg-fullstack) | 小白一句话 → 高质量全栈应用 | `/plugin install lhg-fullstack@lhg-plugs` |

## 自检与反馈

本插件自带质检：每次使用后可跑 `python3 smoke_test.py` 一键验证（JSON 合法、skill/command/agent 完整性、31 条规则、fixtures 命中、hooks 行为）。

发现 bug 或有改进建议，以 `[QC] <一句话问题>` 为标题提交到 https://github.com/lhg-plugs/lhg-video-edit/issues，正文写清"复现步骤 → 实际表现 → 期望表现"。

## 出品：刘洪光

本插件由真人出镜 IP「刘洪光」（安徽合肥）出品，归属 [lhg-skills](https://github.com/lhg-skills)。

- GitHub 主页：https://github.com/lhg-skills —— 全部 skill 开源在此，欢迎 star
- 视频号：搜「刘洪光实名上网」
- 微信：lhgsmsw
