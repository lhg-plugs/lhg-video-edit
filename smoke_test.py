#!/usr/bin/env python3
"""lhg-video-edit 插件冒烟测试：全部绿才算过。

检查项：
 1. 三个 JSON 合法（plugin.json / marketplace.json / hooks.json）
 2. 4 个 SKILL.md 都有 name/description frontmatter，且 150~320 行
 3. 3 个 commands 都有 description frontmatter
 4. 3 个 agents 都有 name/description/tools/model frontmatter
 5. skills 平台中立：不含 Claude Code 专有工具名
 6. fixtures：坏 fixture 的埋点规则必须全部命中且脚本 exit!=0；
    好 fixture 零 blocker 且 exit==0；坏 EDL 单独测 EDL-JSON-001
 7. hooks 脚本：渲染拦截 / 非渲染放行 / 逃生开关 / 无 EDL 提醒放行

用法：python3 smoke_test.py [--repo <插件根目录>]
退出码：0=全绿，1=有失败。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((PASS if cond else FAIL, name, detail))
    return cond


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def frontmatter(path):
    """解析 markdown 顶部 --- YAML 块（只取一层 key: value）。"""
    text = read(path)
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for ln in text[3:end].split("\n"):
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", ln)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)


# 预期的埋点命中（坏 fixture 必须全部命中）
BAD_MUST = {
    "SUB-TYPO-001", "SUB-TIME-001", "SUB-OVERLAP-001", "SUB-LONG-001",
    "SUB-EMPTY-001",
    "EDL-OVER-001", "EDL-ZERO-001", "EDL-RANGE-001", "EDL-ORDER-001",
    "EDL-FADE-001", "EDL-FILLER-001", "EDL-GAP-001",
    "DUR-TARGET-001",
    "COV-SIZE-001", "COV-ASPECT-001",
    "AUD-LOUD-001",
    "CPL-WORD-001", "CPL-RISK-001", "CPL-MUSIC-001",
}
# 平台中立红线：skill 正文不许出现这些 Claude Code 专有表述
NEUTRAL_DENY = ["Task tool", "Bash tool", "Edit tool", "Write tool", "Read tool",
                "AskUserQuestion", "subagent_type", "PreToolUse", "PostToolUse",
                "${CLAUDE_", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    AUDIT = os.path.join(repo, "scripts", "audit")

    # 1. JSON 合法
    for rel in [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                "hooks/hooks.json"]:
        p = os.path.join(repo, rel)
        try:
            d = json.loads(read(p))
            check("JSON 合法: " + rel, True)
            if rel.endswith("plugin.json"):
                check("plugin.json name==lhg-video-edit", d.get("name") == "lhg-video-edit", str(d.get("name")))
                check("plugin.json 有 version/description/author",
                      all(d.get(k) for k in ("version", "description", "author")))
            if rel.endswith("marketplace.json"):
                ps = d.get("plugins", [])
                check("marketplace.json source==./",
                      len(ps) == 1 and ps[0].get("source") == "./" and
                      ps[0].get("name") == "lhg-video-edit", str(ps))
            if rel.endswith("hooks.json"):
                check("hooks.json 顶层有 hooks 包装", "hooks" in d)
                evts = d["hooks"]
                check("hooks.json 有 PreToolUse", "PreToolUse" in evts, str(list(evts)))
        except Exception as e:
            check("JSON 合法: " + rel, False, str(e))

    # 2. SKILL.md frontmatter + 行数
    for skill in ["lhg-ve-transcript", "lhg-ve-script", "lhg-ve-edit",
                  "lhg-ve-audit"]:
        p = os.path.join(repo, "skills", skill, "SKILL.md")
        fm = frontmatter(p)
        check("skill frontmatter: " + skill,
              bool(fm.get("name")) and bool(fm.get("description")),
              "name=%s" % fm.get("name"))
        nlines = len(read(p).split("\n"))
        check("skill 行数 150~320: %s (%d 行)" % (skill, nlines), 150 <= nlines <= 320, str(nlines))
        body = read(p)
        bad_words = [w for w in NEUTRAL_DENY if w in body]
        check("skill 平台中立: " + skill, not bad_words, "命中: %s" % bad_words)
        check("skill 有出品区: " + skill, "出品：刘洪光" in body and "https://github.com/lhg-skills" in body)
        check("skill 有自检与反馈: " + skill, "自检与反馈" in body)

    # 3. commands
    for cmd in ["video-edit", "video-script", "video-audit"]:
        p = os.path.join(repo, "commands", cmd + ".md")
        fm = frontmatter(p)
        check("command description: " + cmd, bool(fm.get("description")), str(fm.get("description"))[:60])

    # 4. agents
    for ag in ["editor", "scripter", "qa-reviewer"]:
        p = os.path.join(repo, "agents", ag + ".md")
        fm = frontmatter(p)
        check("agent frontmatter: " + ag,
              all(fm.get(k) for k in ("name", "description", "tools", "model")),
              str({k: fm.get(k) for k in ("name", "model")}))

    # 5. 审计脚本冒烟
    def audit_hits(target):
        r = run([sys.executable, os.path.join(AUDIT, "video_audit.py"),
                 "--target", os.path.join(repo, target), "--format", "json"])
        try:
            d = json.loads(r.stdout)
        except Exception:
            return None, r.returncode, []
        return d["summary"], r.returncode, [f["rule_id"] for f in d["findings"]]

    s, code, ids = audit_hits("fixtures/bad")
    check("坏 fixture exit!=0", code != 0, "exit=%d" % code)
    check("坏 fixture blocker>0", s and s["blocker"] > 0, str(s))
    missing = BAD_MUST - set(ids)
    check("坏 fixture 埋点全命中 (%d/%d)" % (len(BAD_MUST - missing), len(BAD_MUST)),
          not missing, "缺失: %s" % sorted(missing))

    s, code, ids = audit_hits("fixtures/good")
    check("好 fixture 零 blocker", s and s["blocker"] == 0, str(s))
    check("好 fixture exit==0", code == 0, "exit=%d" % code)

    # EDL-JSON-001 单独覆盖：临时写一个坏 JSON 的 edl.json
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "edl.json"), "w") as fh:
            fh.write("{not json")
        s, code, ids = audit_hits(td)
        check("EDL-JSON-001 命中坏 JSON", "EDL-JSON-001" in ids, str(ids))

    # 规则总数（对外口径：30+ 条）
    n = json.loads(run([sys.executable, os.path.join(AUDIT, "video_audit.py"),
                        "--target", os.path.join(repo, "fixtures/good"),
                        "--format", "json"]).stdout)["summary"]["rules_run"]
    check("规则总数>=30 (%d)" % n, n >= 30, str(n))

    # 6. hooks 脚本
    def hook(script, payload, env=None):
        e = dict(os.environ); e.update(env or {})
        return run([sys.executable, os.path.join(repo, "hooks", script)],
                   input=payload, env=e)

    r = hook("validate_edl_before_render.py", '{"tool_input":{"command":"git status"}}')
    check("hook: 非渲染命令放行", r.returncode == 0 and not r.stdout.strip())

    with tempfile.TemporaryDirectory() as td:
        # 坏 EDL：拷一份坏 fixture 的 edl.json
        import shutil
        shutil.copy(os.path.join(repo, "fixtures/bad/edl.json"),
                    os.path.join(td, "edl.json"))
        r = hook("validate_edl_before_render.py",
                 '{"tool_input":{"command":"ffmpeg -i cut.mp4 -c copy final.mp4"}}',
                 {"CLAUDE_PROJECT_DIR": td})
        try:
            d = json.loads(r.stdout)
            denied = d["hookSpecificOutput"]["permissionDecision"] == "deny"
        except Exception:
            denied = False
        check("hook: 渲染+坏 EDL 拦截", denied, r.stdout[:120])

        # 好 EDL：放行
        shutil.copy(os.path.join(repo, "fixtures/good/edl.json"),
                    os.path.join(td, "edl.json"))
        r = hook("validate_edl_before_render.py",
                 '{"tool_input":{"command":"ffmpeg -i cut.mp4 -c copy final.mp4"}}',
                 {"CLAUDE_PROJECT_DIR": td})
        check("hook: 渲染+好 EDL 放行", r.returncode == 0 and not r.stdout.strip(),
              r.stdout[:80])

        # 逃生开关
        shutil.copy(os.path.join(repo, "fixtures/bad/edl.json"),
                    os.path.join(td, "edl.json"))
        r = hook("validate_edl_before_render.py",
                 '{"tool_input":{"command":"ffmpeg -i cut.mp4 -c copy final.mp4"}}',
                 {"CLAUDE_PROJECT_DIR": td, "LHG_VE_HOOKS_OFF": "1"})
        check("hook: 逃生开关生效", r.returncode == 0 and not r.stdout.strip())

    with tempfile.TemporaryDirectory() as td:
        # 无 EDL：提醒式放行（不拦截）
        r = hook("validate_edl_before_render.py",
                 '{"tool_input":{"command":"ffmpeg -i in.mp4 out.mp4"}}',
                 {"CLAUDE_PROJECT_DIR": td})
        try:
            d = json.loads(r.stdout)
            allowed = d["hookSpecificOutput"]["permissionDecision"] == "allow"
        except Exception:
            allowed = False
        check("hook: 无 EDL 提醒放行", allowed, r.stdout[:80])

    # 报告
    print("=" * 60)
    print("lhg-video-edit 冒烟测试报告")
    print("=" * 60)
    fails = 0
    for st, name, detail in results:
        mark = "✓" if st == PASS else "✗"
        print("%s %s %s" % (mark, st, name))
        if detail and st == FAIL:
            print("    → %s" % detail)
        if st == FAIL:
            fails += 1
    print("=" * 60)
    print("共 %d 项，通过 %d，失败 %d" % (len(results), len(results) - fails, fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
