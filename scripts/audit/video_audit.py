#!/usr/bin/env python3
"""lhg-video-edit 确定性成片审计：31 条规则，零第三方依赖。

扫描交付目录（字幕 .srt/.ass/.vtt、edl.json、封面图、meta.json），
输出 JSON 与人类可读报告；有 blocker 时以 exit code 2 退出
（供 hooks 与 CI 使用）。

用法：
    python3 video_audit.py --target <目录> [--format json|text] [--fail-on blocker|warning|nit]

规则文案均为本项目原创（方法论思路受 browser-use/video-use 与
latent-spaces/brag 等 MIT 开源项目启发，未复制任何第三方原文；
详见仓库 ATTRIBUTION.md）。
"""

import argparse
import json
import os
import re
import struct
import sys
import zlib

VERSION = "1.0.0"
TOOL = "lhg-video-edit/video-audit"

SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", "build"}

SUB_EXTS = {".srt", ".ass", ".vtt"}
IMG_EXTS = {".png", ".jpg", ".jpeg"}


class Finding:
    __slots__ = ("rule_id", "severity", "category", "title", "file", "line", "snippet", "detail")

    def __init__(self, rule_id, severity, category, title, file, line, snippet, detail):
        self.rule_id = rule_id
        self.severity = severity
        self.category = category
        self.title = title
        self.file = file
        self.line = line
        self.snippet = snippet
        self.detail = detail

    def to_dict(self):
        return {
            "rule_id": self.rule_id, "severity": self.severity,
            "category": self.category, "title": self.title,
            "file": self.file, "line": self.line,
            "snippet": self.snippet, "detail": self.detail,
        }


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        return None
    except OSError:
        return ""


def collect(target):
    subs, edls, covers, metas = [], [], [], []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            p = os.path.join(root, f)
            _, ext = os.path.splitext(f)
            ext = ext.lower()
            if ext in SUB_EXTS:
                subs.append(p)
            elif f.lower() in ("edl.json",) or f.lower().endswith(".edl.json"):
                edls.append(p)
            elif ext in IMG_EXTS and "cover" in f.lower():
                covers.append(p)
            elif f.lower() == "meta.json":
                metas.append(p)
    return {"subs": sorted(subs), "edls": sorted(edls),
            "covers": sorted(covers), "metas": sorted(metas)}


# ---------------------------------------------------------------- 规则注册表
RULES = []
_RULE_BY_ID = {}


def rule(rule_id, severity, category, title, detail):
    def deco(fn):
        r = {"id": rule_id, "severity": severity, "category": category,
             "title": title, "detail": detail}
        _RULE_BY_ID[rule_id] = r
        r["check"] = fn
        RULES.append(r)
        return fn
    return deco


def _mk(rule_id, path, line, snippet):
    r = _RULE_BY_ID[rule_id]
    return Finding(r["id"], r["severity"], r["category"], r["title"],
                   path, line, snippet[:160], r["detail"])


# ---------------------------------------------------------------- 自建表
# 常见错别字表（错 -> 对），持续扩充。只收"无歧义"的，拿不准的不进表。
TYPO_TABLE = [
    ("做为", "作为"), ("已近", "已经"), ("在作", "在做"), ("必须品", "必需品"),
    ("按步就班", "按部就班"), ("迫不急待", "迫不及待"), ("再接再励", "再接再厉"),
    ("一愁莫展", "一筹莫展"), ("穿流不息", "川流不息"), ("金壁辉煌", "金碧辉煌"),
    ("走头无路", "走投无路"), ("默默无蚊", "默默无闻"), ("欢渡", "欢度"),
    ("幅射", "辐射"), ("兰天", "蓝天"), ("大姆指", "大拇指"), ("欧州", "欧洲"),
    ("冒然", "贸然"), ("既使", "即使"), ("直接了当", "直截了当"),
    ("甘败下风", "甘拜下风"), ("不能自己", "不能自已"), ("负作用", "副作用"),
    ("黄梁一梦", "黄粱一梦"), ("渲然大波", "轩然大波"),
]
# 极限词 / 违禁词（广告法高频）——启发式，有误报可能，见误报处理
BANNED_WORDS = [
    "最牛", "最佳", "第一", "顶级", "国家级", "首选", "首家", "唯一",
    "绝无仅有", "史无前例", "万能", "根治", "特效", "祖传", "宫廷",
    "全网最低", "抄底价", "最后一天",
]
# 投资话术（金融题材红线）
RISKY_FINANCE = ["稳赚", "必涨", "保本", "零风险", "翻倍收益", "内幕消息", "包赚"]
# 口头禅（与 lhg-ve-transcript 口头禅库一级词对齐）
FILLER_WORDS = ["那个那个", "这个这个", "就是说就是说"]

SRT_TS = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _ts_to_sec(m, base=0):
    g = [int(m.group(i)) for i in range(1 + base, 5 + base)]
    g2 = [int(m.group(i)) for i in range(5 + base, 9 + base)]
    return (g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0,
            g2[0] * 3600 + g2[1] * 60 + g2[2] + g2[3] / 1000.0)


def parse_srt(text):
    """返回 ([(序号, 开始秒, 结束秒, 文本, 起始行号)], [坏行号...])。"""
    entries, bad_lines = [], []
    blocks = re.split(r"\n\s*\n", text.strip())
    lineno = 1
    for b in blocks:
        lines = b.strip().split("\n")
        start_line = lineno
        lineno += len(lines) + 1
        if len(lines) < 2:
            continue
        m = SRT_TS.search(lines[1])
        if not m:
            # 序号行之后不是合法时间轴 -> 时间格式问题
            bad_lines.append(start_line + 1)
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            idx = -1
        st, en = _ts_to_sec(m)
        entries.append((idx, st, en, " ".join(l.strip() for l in lines[2:]),
                        start_line))
    return entries, bad_lines


def png_size(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(33)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h = struct.unpack(">II", head[16:24])
        return (w, h)
    except OSError:
        return None


def jpeg_size(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        if data[:2] != b"\xff\xd8":
            return None
        i = 2
        while i < len(data) - 1:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return (w, h)
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            ln = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + ln
        return None
    except OSError:
        return None


def image_size(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return png_size(path)
    if ext in (".jpg", ".jpeg"):
        return jpeg_size(path)
    return None


# ================================================================ 字幕规则

@rule("SUB-TYPO-001", "blocker", "字幕", "疑似错别字",
      "命中自建常见错别字表。错别字是成片最低级的翻车，发布前必须改。")
def r_sub_typo(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        text = read_text(p)
        if text is None:
            continue
        entries, _ = parse_srt(text)
        for idx, st, en, sent, ln in entries:
            for wrong, right in TYPO_TABLE:
                if wrong in sent:
                    out.append(_mk("SUB-TYPO-001", p, ln,
                                   "「%s」疑似应为「%s」：%s" % (wrong, right, sent)))
                    break
    return out


@rule("SUB-TIME-001", "blocker", "字幕", "时间轴格式非法",
      "字幕条时间轴不是合法的 HH:MM:SS,mmm --> HH:MM:SS,mmm 格式，播放器会跳过该条。")
def r_sub_time(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        text = read_text(p)
        if text is None:
            continue
        _, bad = parse_srt(text)
        for ln in bad:
            out.append(_mk("SUB-TIME-001", p, ln, "时间轴格式非法"))
    return out


@rule("SUB-OVERLAP-001", "blocker", "字幕", "字幕时间轴重叠",
      "两条字幕时间重叠，播放时会互相覆盖、闪烁。")
def r_sub_overlap(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        text = read_text(p)
        if text is None:
            continue
        entries, _ = parse_srt(text)
        for (i1, s1, e1, t1, l1), (i2, s2, e2, t2, l2) in zip(entries, entries[1:]):
            if s2 < e1 - 1e-6:
                out.append(_mk("SUB-OVERLAP-001", p, l2,
                               "与上一条重叠 %.1fs" % (e1 - s2)))
    return out


@rule("SUB-ENC-001", "blocker", "字幕", "非 UTF-8 编码",
      "字幕不是 UTF-8 编码，烧录/平台上传可能乱码。转存为 UTF-8。")
def r_sub_enc(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        if read_text(p) is None:
            out.append(_mk("SUB-ENC-001", p, 1, "文件不是合法 UTF-8"))
    return out


@rule("SUB-SEQ-001", "warning", "字幕", "序号不连续",
      "字幕序号跳号或重复，通常是手动删条后没重排。不影响播放，但建议整理。")
def r_sub_seq(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        text = read_text(p)
        if text is None:
            continue
        entries, _ = parse_srt(text)
        want = 1
        for idx, st, en, sent, ln in entries:
            if idx != want:
                out.append(_mk("SUB-SEQ-001", p, ln,
                               "序号为 %d，应为 %d" % (idx, want)))
                break
            want += 1
    return out


@rule("SUB-LONG-001", "warning", "字幕", "单行字幕超长",
      "单行超过 18 个字，手机端会被迫换行或缩到看不清。拆成两行。")
def r_sub_long(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        text = read_text(p)
        if text is None:
            continue
        entries, _ = parse_srt(text)
        for idx, st, en, sent, ln in entries:
            s = sent.strip()
            if len(s) > 18:
                out.append(_mk("SUB-LONG-001", p, ln,
                               "%d 字：%s" % (len(s), s)))
    return out


@rule("SUB-SPD-001", "warning", "字幕", "字幕停留异常",
      "单条停留 <0.6 秒（看不清）或 >8 秒（像卡住）。")
def r_sub_spd(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        text = read_text(p)
        if text is None:
            continue
        entries, _ = parse_srt(text)
        for idx, st, en, sent, ln in entries:
            dur = en - st
            if dur < 0.6 - 1e-9:
                out.append(_mk("SUB-SPD-001", p, ln, "停留仅 %.1fs，看不清" % dur))
            elif dur > 8.0 + 1e-9:
                out.append(_mk("SUB-SPD-001", p, ln, "停留 %.1fs，像卡住" % dur))
    return out


@rule("SUB-EMPTY-001", "warning", "字幕", "空字幕条",
      "有时间轴但无文字，通常是误删文字残留。删掉该条。")
def r_sub_empty(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        text = read_text(p)
        if text is None:
            continue
        entries, _ = parse_srt(text)
        for idx, st, en, sent, ln in entries:
            if not sent.strip():
                out.append(_mk("SUB-EMPTY-001", p, ln, "空字幕条"))
    return out


# ================================================================ EDL 规则

def _load_edl(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:
        return None, str(e)


@rule("EDL-JSON-001", "blocker", "EDL", "EDL 不是合法 JSON",
      "EDL 解析失败，渲染流水线无法执行。检查逗号/引号。")
def r_edl_json(ctx):
    out = []
    for p in ctx["files"]["edls"]:
        _, err = _load_edl(p)
        if err:
            out.append(_mk("EDL-JSON-001", p, 1, err))
    return out


def _edl_segs(ctx):
    """返回 [(edl路径, segments列表)]，解析失败的跳过。"""
    out = []
    for p in ctx["files"]["edls"]:
        edl, err = _load_edl(p)
        if err:
            continue
        segs = edl.get("segments")
        if isinstance(segs, list):
            out.append((p, segs, edl))
    return out


@rule("EDL-OVER-001", "blocker", "EDL", "EDL 片段重叠",
      "两个片段时间重叠，渲染会重复/错乱。")
def r_edl_over(ctx):
    out = []
    for p, segs, _ in _edl_segs(ctx):
        prev_end = None
        for i, s in enumerate(segs):
            try:
                st, en = float(s["start"]), float(s["end"])
            except Exception:
                continue
            if prev_end is not None and st < prev_end - 1e-6:
                out.append(_mk("EDL-OVER-001", p, 1,
                               "第 %d 段与上一段重叠" % (i + 1)))
            prev_end = en if prev_end is None else max(prev_end, en)
    return out


@rule("EDL-ZERO-001", "blocker", "EDL", "EDL 零时长/负时长片段",
      "片段 start 不小于 end，渲染会失败或产生空帧。")
def r_edl_zero(ctx):
    out = []
    for p, segs, _ in _edl_segs(ctx):
        for i, s in enumerate(segs):
            try:
                st, en = float(s["start"]), float(s["end"])
            except Exception:
                continue
            if not st < en:
                out.append(_mk("EDL-ZERO-001", p, 1,
                               "第 %d 段 start=%.2f end=%.2f" % (i + 1, st, en)))
    return out


@rule("EDL-RANGE-001", "blocker", "EDL", "EDL 片段超出源时长",
      "片段 end 超过 source_duration_sec，渲染会黑屏/报错。")
def r_edl_range(ctx):
    out = []
    for p, segs, edl in _edl_segs(ctx):
        src = edl.get("source_duration_sec")
        if src is None:
            continue
        try:
            src = float(src)
        except Exception:
            continue
        for i, s in enumerate(segs):
            try:
                en = float(s["end"])
            except Exception:
                continue
            if en > src + 1e-6:
                out.append(_mk("EDL-RANGE-001", p, 1,
                               "第 %d 段 end=%.1f 超出源时长 %.1f" % (i + 1, en, src)))
    return out


@rule("EDL-ORDER-001", "warning", "EDL", "EDL 片段顺序错乱",
      "片段未按 start 升序排列，可读性差且易藏重叠 bug。重排。")
def r_edl_order(ctx):
    out = []
    for p, segs, _ in _edl_segs(ctx):
        starts = []
        ok = True
        for s in segs:
            try:
                starts.append(float(s["start"]))
            except Exception:
                ok = False
                break
        if ok and starts != sorted(starts):
            out.append(_mk("EDL-ORDER-001", p, 1, "片段未按 start 升序"))
    return out


@rule("EDL-FADE-001", "warning", "EDL", "切点缺少音频淡变",
      "keep 段未声明 fade_ms，切点硬接容易爆音。建议 30ms 淡变。")
def r_edl_fade(ctx):
    out = []
    for p, segs, _ in _edl_segs(ctx):
        for i, s in enumerate(segs):
            if s.get("action") == "keep" and "fade_ms" not in s:
                out.append(_mk("EDL-FADE-001", p, 1,
                               "第 %d 段 keep 无 fade_ms" % (i + 1)))
    return out


@rule("EDL-FILLER-001", "warning", "EDL", "保留段残留口头禅",
      "keep 段文本含高频口头禅（那个那个/这个这个/就是说就是说），疑似漏删。")
def r_edl_filler(ctx):
    out = []
    for p, segs, _ in _edl_segs(ctx):
        for i, s in enumerate(segs):
            if s.get("action") == "keep":
                t = str(s.get("text", ""))
                hit = [w for w in FILLER_WORDS if w in t]
                if hit:
                    out.append(_mk("EDL-FILLER-001", p, 1,
                                   "第 %d 段含口头禅：%s" % (i + 1, "、".join(hit))))
    return out


@rule("EDL-GAP-001", "warning", "EDL", "残留大段静音",
      "标记为静音的 keep 段超过 3 秒，疑似忘词停顿漏剪。")
def r_edl_gap(ctx):
    out = []
    for p, segs, _ in _edl_segs(ctx):
        for i, s in enumerate(segs):
            if s.get("action") == "keep" and s.get("audio") == "silence":
                try:
                    dur = float(s["end"]) - float(s["start"])
                except Exception:
                    continue
                if dur > 3.0:
                    out.append(_mk("EDL-GAP-001", p, 1,
                                   "第 %d 段静音 %.1fs" % (i + 1, dur)))
    return out


# ================================================================ 时长规则

def _meta(ctx):
    for p in ctx["files"]["metas"]:
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh), p
        except Exception:
            continue
    return {}, None


@rule("DUR-TARGET-001", "blocker", "时长", "成片时长偏离目标",
      "成片时长与目标时长偏差超过 10%。平台按时长分发，偏离太多等于白剪。")
def r_dur_target(ctx):
    meta, p = _meta(ctx)
    try:
        dur = float(meta["duration_sec"])
        tgt = float(meta["target_sec"])
    except (KeyError, TypeError, ValueError):
        return []
    if tgt <= 0:
        return []
    if abs(dur - tgt) / tgt > 0.10:
        return [_mk("DUR-TARGET-001", p or ctx["target"], 1,
                    "成片 %.0fs，目标 %.0fs，偏差 %.0f%%"
                    % (dur, tgt, abs(dur - tgt) / tgt * 100))]
    return []


@rule("DUR-SHORT-001", "warning", "时长", "成片过短",
      "成片短于 15 秒，信息密度不足，慎发。")
def r_dur_short(ctx):
    meta, p = _meta(ctx)
    try:
        dur = float(meta["duration_sec"])
    except (KeyError, TypeError, ValueError):
        return []
    if dur < 15:
        return [_mk("DUR-SHORT-001", p or ctx["target"], 1,
                    "成片仅 %.0fs" % dur)]
    return []


# ================================================================ 封面规则

@rule("COV-MISSING-001", "warning", "封面", "缺少封面图",
      "交付目录没有 cover.* 封面图。封面决定点击率，不许裸发。")
def r_cov_missing(ctx):
    if not ctx["files"]["covers"] and (
            ctx["files"]["subs"] or ctx["files"]["edls"] or ctx["files"]["metas"]):
        return [_mk("COV-MISSING-001", ctx["target"], 1, "未找到 cover.* 封面图")]
    return []


@rule("COV-SIZE-001", "blocker", "封面", "封面尺寸不是 1080x1920",
      "竖屏封面必须 1080x1920。尺寸不对会被平台拉伸/裁切。")
def r_cov_size(ctx):
    out = []
    for p in ctx["files"]["covers"]:
        wh = image_size(p)
        if wh and wh != (1080, 1920):
            out.append(_mk("COV-SIZE-001", p, 1,
                           "实际 %dx%d，应为 1080x1920" % wh))
    return out


@rule("COV-ASPECT-001", "blocker", "封面", "封面长宽比不是 9:16",
      "长宽比偏离 9:16 超过 2%，竖屏展示会被裁掉关键内容。")
def r_cov_aspect(ctx):
    out = []
    for p in ctx["files"]["covers"]:
        wh = image_size(p)
        if wh and wh != (1080, 1920):
            w, h = wh
            if h > 0 and abs(w / h - 9 / 16) / (9 / 16) > 0.02:
                out.append(_mk("COV-ASPECT-001", p, 1,
                               "长宽比 %.3f，偏离 9:16" % (w / h)))
    return out


@rule("COV-BIG-001", "warning", "封面", "封面文件过大",
      "封面超过 2MB，部分平台上传会压缩或失败。")
def r_cov_big(ctx):
    out = []
    for p in ctx["files"]["covers"]:
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue
        if sz > 2 * 1024 * 1024:
            out.append(_mk("COV-BIG-001", p, 1, "%.1fMB" % (sz / 1024 / 1024)))
    return out


@rule("COV-FMT-001", "warning", "封面", "封面格式建议",
      "封面不是 PNG/JPG。部分平台对 webp/avif 封面支持不稳定。")
def r_cov_fmt(ctx):
    out = []
    for p in ctx["files"]["covers"]:
        ext = os.path.splitext(p)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg"):
            out.append(_mk("COV-FMT-001", p, 1, "格式为 %s" % ext))
    return out


# ================================================================ 音频规则

@rule("AUD-LOUD-001", "blocker", "音频", "缺少响度归一参数",
      "meta.json 未声明 loudnorm 参数。成片音量忽大忽小是廉价感来源，必须归一。")
def r_aud_loud(ctx):
    meta, p = _meta(ctx)
    if (ctx["files"]["metas"] or ctx["files"]["edls"]) and not meta.get("loudnorm"):
        return [_mk("AUD-LOUD-001", p or ctx["target"], 1,
                    "meta.json 缺少 loudnorm（如 I=-14/TP=-1.5/LRA=11）")]
    return []


@rule("AUD-LUFS-001", "warning", "音频", "目标响度不是 -14 LUFS",
      "短视频平台标准 -14 LUFS。偏差超过 ±1 会被平台二次压限，音质受损。")
def r_aud_lufs(ctx):
    meta, p = _meta(ctx)
    ln = meta.get("loudnorm") or {}
    try:
        i = float(ln.get("I"))
    except (TypeError, ValueError):
        return []
    if abs(i - (-14)) > 1.0:
        return [_mk("AUD-LUFS-001", p or ctx["target"], 1, "I=%.1f" % i)]
    return []


@rule("AUD-PEAK-001", "warning", "音频", "真峰值超标",
      "TP 高于 -1 dBTP，转码后可能削波。")
def r_aud_peak(ctx):
    meta, p = _meta(ctx)
    ln = meta.get("loudnorm") or {}
    try:
        tp = float(ln.get("TP"))
    except (TypeError, ValueError):
        return []
    if tp > -1.0:
        return [_mk("AUD-PEAK-001", p or ctx["target"], 1, "TP=%.1f dBTP" % tp)]
    return []


@rule("AUD-CH-001", "warning", "音频", "声道数异常",
      "声道不是立体声（2）。单声道在部分设备上只有一边响。")
def r_aud_ch(ctx):
    meta, p = _meta(ctx)
    ch = meta.get("channels")
    if ch is not None:
        try:
            if int(ch) != 2:
                return [_mk("AUD-CH-001", p or ctx["target"], 1,
                            "channels=%s" % ch)]
        except (TypeError, ValueError):
            pass
    return []


# ================================================================ 合规规则

def _all_sub_text(ctx):
    out = []
    for p in ctx["files"]["subs"]:
        text = read_text(p)
        if text is None:
            continue
        entries, _ = parse_srt(text)
        for idx, st, en, sent, ln in entries:
            out.append((p, ln, sent))
    return out


@rule("CPL-WORD-001", "blocker", "合规", "极限词/违禁词",
      "命中广告法高频极限词。平台审核与职业打假人的重点靶子，靠换词修。")
def r_cpl_word(ctx):
    out = []
    for p, ln, sent in _all_sub_text(ctx):
        hit = [w for w in BANNED_WORDS if w in sent]
        if hit:
            out.append(_mk("CPL-WORD-001", p, ln,
                           "命中：%s" % "、".join(hit)))
    return out


@rule("CPL-RISK-001", "blocker", "合规", "投资话术",
      "字幕含稳赚/必涨/保本类话术。金融题材红线，平台与监管双罚。")
def r_cpl_risk(ctx):
    out = []
    for p, ln, sent in _all_sub_text(ctx):
        hit = [w for w in RISKY_FINANCE if w in sent]
        if hit:
            out.append(_mk("CPL-RISK-001", p, ln,
                           "命中：%s" % "、".join(hit)))
    return out


@rule("CPL-MUSIC-001", "warning", "合规", "版权音乐来源不明",
      "meta.json 的 music_source 未声明或含糊，写[网上下的]不算来源。"
      "BGM 三选一：自制 / 已购版权 / 平台免费曲库。")
def r_cpl_music(ctx):
    meta, p = _meta(ctx)
    if not ctx["files"]["metas"]:
        return []
    src = str(meta.get("music_source", "")).strip()
    vague = ("未确认", "网上", "未知", "抖音热歌", "随便")
    if not src or any(v in src for v in vague):
        return [_mk("CPL-MUSIC-001", p or ctx["target"], 1,
                    "music_source=%r" % src)]
    return []


@rule("CPL-TITLE-001", "warning", "合规", "标题含极限词",
      "meta.json 的 title 含极限词/违禁词。标题是审核第一眼。")
def r_cpl_title(ctx):
    meta, p = _meta(ctx)
    title = str(meta.get("title", ""))
    hit = [w for w in BANNED_WORDS if w in title]
    if hit:
        return [_mk("CPL-TITLE-001", p or ctx["target"], 1,
                    "标题命中：%s" % "、".join(hit))]
    return []


# ---------------------------------------------------------------- 主流程

def run_checks(ctx):
    findings = []
    for r in RULES:
        try:
            findings.extend(r["check"](ctx) or [])
        except Exception as e:
            findings.append(Finding("INTERNAL", "warning", "内部",
                                    "规则 %s 执行异常" % r["id"], ctx["target"],
                                    1, str(e)[:120], "规则自身 bug，请提 issue"))
    sev_rank = {"blocker": 0, "warning": 1, "nit": 2}
    findings.sort(key=lambda f: (sev_rank.get(f.severity, 3), f.rule_id, f.file))
    return findings


def summarize(findings):
    s = {"blocker": 0, "warning": 0, "nit": 0, "rules_run": len(RULES)}
    for f in findings:
        if f.severity in s:
            s[f.severity] += 1
    s["total"] = len(findings)
    return s


def main():
    ap = argparse.ArgumentParser(description="lhg-video-edit 确定性成片审计")
    ap.add_argument("--target", required=True, help="交付目录")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--fail-on", choices=["blocker", "warning", "nit"],
                    default="blocker")
    args = ap.parse_args()

    target = os.path.abspath(args.target)
    ctx = {"target": target, "files": collect(target)}
    findings = run_checks(ctx)
    summary = summarize(findings)

    payload = {
        "tool": TOOL, "version": VERSION, "target": target,
        "summary": summary,
        "findings": [f.to_dict() for f in findings],
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("== lhg-video-edit 成片审计 ==")
        print("目标：%s" % target)
        print("规则：%d 条 | blocker=%d warning=%d nit=%d" % (
            summary["rules_run"], summary["blocker"],
            summary["warning"], summary["nit"]))
        for f in findings:
            print("[%s][%s] %s:%s %s -- %s" % (
                f.severity, f.rule_id, os.path.relpath(f.file, target)
                if f.file.startswith(target) else f.file,
                f.line, f.title, f.snippet))

    order = {"blocker": 0, "warning": 1, "nit": 2}
    threshold = order[args.fail_on]
    bad = any(order.get(f.severity, 9) <= threshold for f in findings)
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
