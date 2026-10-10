#!/usr/bin/env python3
"""lhg-video-edit 硬门：渲染 final.mp4 前校验 EDL 有效性。

触发：PreToolUse / Bash。脚本先判断本次 Bash 命令是否为"渲染"
（ffmpeg 输出 .mp4，或命令含 render/final.mp4 等渲染意图），不是则
0 开销直接放行；是则查找并校验交付目录下的 edl.json。

校验项：JSON 合法、segments 非空、每段 start<end、段内不重叠、
段不超出源时长（若声明了 source_duration_sec）。

逃生方式（按推荐度排序）：
  1. 修好 EDL 后重新渲染（推荐）。
  2. 紧急情况：LHG_VE_HOOKS_OFF=1 <渲染命令>（单次豁免本次 hook）。
  3. /plugin disable lhg-video-edit（整个插件停用，hooks 不再触发）。

设计原则：脚本内部出错（找不到 EDL、超时、解析失败等）时 fail-open
直接放行，不因插件自身故障骚扰用户；真正的门禁在
/lhg-video-edit:video-audit。找不到 EDL 文件时只做提醒式放行
（additionalContext），不拦截——因为用户可能在渲染与本插件无关的视频。
零第三方依赖。
"""

import json
import os
import re
import sys

RENDER_RE = re.compile(
    r"(?<![\w-])(ffmpeg|render|video-edit)\b.*\.(mp4|mov|mkv)\b"
    r"|\bfinal\.mp4\b",
    re.I,
)
EDL_NAMES = ("edl.json", "EDL.json")


def find_edl(project_dir):
    for name in EDL_NAMES:
        p = os.path.join(project_dir, name)
        if os.path.isfile(p):
            return p
    # 兜底：目录下唯一的 *.edl.json
    cands = [f for f in os.listdir(project_dir)
             if f.endswith(".edl.json") and os.path.isfile(os.path.join(project_dir, f))]
    if len(cands) == 1:
        return os.path.join(project_dir, cands[0])
    return None


def validate_edl(path):
    """返回 (ok, [问题列表])。"""
    problems = []
    try:
        with open(path, encoding="utf-8") as fh:
            edl = json.load(fh)
    except Exception as e:
        return False, ["EDL 不是合法 JSON：%s" % e]
    segs = edl.get("segments")
    if not isinstance(segs, list) or not segs:
        return False, ["EDL 缺少 segments 或为空"]
    src_dur = edl.get("source_duration_sec")
    prev_end = None
    for i, s in enumerate(segs):
        tag = "第 %d 段" % (i + 1)
        try:
            st, en = float(s["start"]), float(s["end"])
        except Exception:
            problems.append("%s start/end 缺失或非数字" % tag)
            continue
        if not st < en:
            problems.append("%s start(%.2f) 不小于 end(%.2f)：零时长或负时长"
                            % (tag, st, en))
        if src_dur is not None:
            try:
                if en > float(src_dur) + 1e-6:
                    problems.append("%s end(%.2f) 超出源时长(%.2f)"
                                    % (tag, en, float(src_dur)))
            except Exception:
                pass
        if prev_end is not None and st < prev_end - 1e-6:
            problems.append("%s start(%.2f) 与上一段重叠（上一段 end=%.2f）"
                            % (tag, st, prev_end))
        prev_end = en if prev_end is None else max(prev_end, en)
    return (not problems), problems


def main() -> int:
    # 逃生开关
    if os.environ.get("LHG_VE_HOOKS_OFF") == "1":
        return 0

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # 输入解析失败：fail-open

    tool_input = payload.get("tool_input", {}) or {}
    command = tool_input.get("command", "") or ""

    # 非渲染命令：快速放行
    if not RENDER_RE.search(command):
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    edl_path = find_edl(project_dir)

    if edl_path is None:
        # 找不到 EDL：提醒式放行，不拦截（可能渲染的是无关视频）
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": (
                    "提醒：本次渲染未在当前目录找到 edl.json。"
                    "如果是用 lhg-video-edit 剪口播，请先写 EDL（见 skill lhg-ve-edit），"
                    "否则跳过此提醒。"
                ),
            }
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        return 0

    try:
        ok, problems = validate_edl(edl_path)
    except Exception:
        return 0  # 校验自身出错：fail-open

    if ok:
        return 0

    lines = [
        "渲染被 lhg-video-edit 硬门拦截：EDL 校验发现 %d 个问题，修好再渲染。"
        % len(problems),
        "EDL 文件：%s" % edl_path,
        "",
    ]
    for p in problems[:10]:
        lines.append("- " + p)
    if len(problems) > 10:
        lines.append("…另有 %d 个" % (len(problems) - 10))
    lines += [
        "",
        "修复方式：按 lhg-ve-edit 第 2 节 EDL 规范修正后重新渲染；",
        "紧急豁免（单次）：LHG_VE_HOOKS_OFF=1 <渲染命令>",
    ]
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "\n".join(lines),
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
