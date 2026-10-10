# 灵感来源与致谢（Attribution）

本插件的**方法论灵感**来自以下优秀的开源项目，**所有实现代码、检测规则与文案均为原创**，未复制任何第三方的原文案与代码。

| 项目 | 作者 / 组织 | 许可 | 链接 | 借鉴了什么思路 |
|---|---|---|---|---|
| video-use | browser-use 组织 | MIT | https://github.com/browser-use/video-use | "素材→一句话→final.mp4"流水线思想：转录优先、显式 EDL（Edit Decision List）、渲染前自检；本插件的 `lhg-ve-transcript` / `lhg-ve-edit` / 渲染前 EDL 校验 hook 受其启发。**实现与文案全部原创** |
| brag | latent-spaces（Shunit Haviv Hakimi） | MIT | https://github.com/latent-spaces/brag | "一键成片"方法论：分镜规划先行、时长窗口约束、渲染后校验再交付；本插件"先写 EDL 再渲染、自检重渲染"流程受其启发。**实现与文案全部原创** |

热度核实（2026-10-11 实查）：
- `browser-use/video-use`：MIT 许可多方一致；star 数约 25.1k（第三方聚合 avalonlee/astracraft-program，核验日期 2026-09-19），另一聚合源 rivendale/opensource 于 2026-10-02 记录为 28.4k——star 数随时间浮动，取约数表述。
- `latent-spaces/brag`：MIT 许可（经 gittrend.io 与 coco-research PR #80 的 `gh api` 双重核验）；star 数约 14.8k（gittrend.io，2026-10-10）。调研报告（2026-10-10）中记为 11k+，为当时数据。

## 声明

1. **借鉴思路，实现与文案均为原创**：以上项目的具体文案、规则原文、代码实现均未被复制。本插件的 skill 方法论文案、审计规则、命令流程、hook 脚本均为独立撰写。
2. **许可合规**：上述项目均为 MIT 许可，允许在保留声明的前提下进行思路借鉴与二次创作。本文件即为保留声明的一部分。
3. **商标与归属**：各项目名称与作者署名归其各自所有者所有。
4. **未核实项**：调研报告中提及的中文创作者 skill 实践（orange-book 中的 /videooutline、/scriptpolish）与 alexlarcheveque/claude-watch 的钩子拆解思路，因未能核实其开源许可，**本插件未借鉴**，口播脚本 skill（lhg-ve-script）的方法论为独立撰写。

## 本插件自身的许可

本插件原创部分采用 MIT 许可（见 `LICENSE` 文件），版权所有：刘洪光（https://github.com/lhg-skills）。
