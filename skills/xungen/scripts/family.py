#!/usr/bin/env python3
"""Check, draw and export a Chinese family tree kept as JSON.

  family.py check  family.json            # 检查：关系、辈分、字辈、年份、出处、在世者
  family.py svg    family.json -o tree.svg [--public]
  family.py gedcom family.json -o family.ged [--public]
  family.py table  family.json -o tree.md  [--public]
  family.py all    family.json -o out/     [--public]

--public hides people who are or may be alive (name, dates, notes), for
anything you plan to share. See references/privacy.md.

The JSON format is described in references/data-format.md and shown in
assets/family.example.json. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import sys
from dataclasses import dataclass
from pathlib import Path

THIS_YEAR = _dt.date.today().year
COMPOUND_SURNAMES = (
    "欧阳 司马 诸葛 上官 东方 皇甫 尉迟 公孙 慕容 长孙 宇文 司徒 令狐 夏侯 澹台 端木 轩辕 呼延 南宫 "
    "万俟 闻人 东郭 西门 百里 歐陽 司馬 諸葛 東方 尉遲 長孫 令狐 夏侯 軒轅 南宮 聞人 東郭"
).split()
STATUS_ZH = {
    "corroborated": "互证", "single": "单一来源", "oral": "口述/无出处",
    "hypothesis": "推测", "contradicted": "有矛盾",
}


# ------------------------------------------------------------------ data


@dataclass
class Issue:
    level: str  # error | warn | info | todo
    code: str
    who: str
    msg: str
    pid: str = ""


class Tree:
    def __init__(self, data: dict):
        self.data = data
        self.title = data.get("title") or "家族世系"
        self.people: list[dict] = data.get("people", [])
        self.by_id: dict[str, dict] = {}
        self.dupe_ids: list[str] = []
        for p in self.people:
            pid = str(p.get("id", ""))
            if pid in self.by_id:
                self.dupe_ids.append(pid)
            self.by_id[pid] = p
        self.sources = {str(s.get("id")): s for s in data.get("sources", [])}
        zb = data.get("zibei") or {}
        self.zibei_chars = list(zb.get("chars", ""))
        self.zibei_start = zb.get("start_generation")
        self._infer_generations()

    # relationships -------------------------------------------------
    def parent_ids(self, p: dict) -> list[str]:
        return [x for x in (p.get("father"), p.get("mother")) if x]

    def children(self, pid: str) -> list[dict]:
        kids = [c for c in self.people if pid in (c.get("father"), c.get("mother"))]
        return sorted(kids, key=lambda c: (year(c, "birth") or 9999, self.people.index(c)))

    def spouses(self, pid: str) -> list[str]:
        out: list[str] = []
        p = self.by_id.get(pid, {})
        for s in p.get("spouses", []) or []:
            if s not in out:
                out.append(s)
        for q in self.people:
            if pid in (q.get("spouses") or []) and q["id"] not in out:
                out.append(q["id"])
        for c in self.people:
            f, m = c.get("father"), c.get("mother")
            if f == pid and m and m not in out:
                out.append(m)
            if m == pid and f and f not in out:
                out.append(f)
        return [s for s in out if s in self.by_id]

    def has_parents_in_tree(self, p: dict) -> bool:
        return any(x in self.by_id for x in self.parent_ids(p))

    # generations ---------------------------------------------------
    def _infer_generations(self) -> None:
        self.gen: dict[str, int] = {}
        for p in self.people:
            if isinstance(p.get("generation"), int):
                self.gen[p["id"]] = p["generation"]
        changed = True
        while changed:
            changed = False
            for p in self.people:
                pid = p["id"]
                if pid in self.gen:
                    continue
                for par in self.parent_ids(p):
                    if par in self.gen:
                        self.gen[pid] = self.gen[par] + 1
                        changed = True
                        break
                if pid in self.gen:
                    continue
                for c in self.children(pid):
                    if c["id"] in self.gen:
                        self.gen[pid] = self.gen[c["id"]] - 1
                        changed = True
                        break
                if pid in self.gen:
                    continue
                for s in self.spouses(pid):
                    if s in self.gen:
                        self.gen[pid] = self.gen[s]
                        changed = True
                        break
        # anything still unknown: place by depth from a root
        for p in self.people:
            if p["id"] not in self.gen:
                d, cur, seen = 0, p, set()
                while True:
                    par = next((x for x in self.parent_ids(cur) if x in self.by_id), None)
                    if not par or par in seen:
                        break
                    seen.add(par)
                    d += 1
                    cur = self.by_id[par]
                self.gen[p["id"]] = d + 1

    def zibei_for(self, generation: int) -> str | None:
        if not self.zibei_chars or not isinstance(self.zibei_start, int):
            return None
        i = generation - self.zibei_start
        return self.zibei_chars[i] if 0 <= i < len(self.zibei_chars) else None

    def married_in(self) -> set[str]:
        """People who joined the family by marriage: drawn beside their partner, no 字辈."""
        if hasattr(self, "_married_in"):
            return self._married_in
        mi: set[str] = set()
        for p in self.people:
            if self.has_parents_in_tree(p):
                continue
            partners = [self.by_id[s] for s in self.spouses(p["id"])]
            if any(self.has_parents_in_tree(q) for q in partners):
                mi.add(p["id"])
            elif p.get("sex") == "F" and any(q.get("sex") == "M" for q in partners):
                mi.add(p["id"])  # a wife whose husband is also a root
        for pid in list(mi):  # someone has to anchor each couple
            if not any(s not in mi for s in self.spouses(pid)):
                mi.discard(pid)
        self._married_in = mi
        return mi

    def zibei_of(self, p: dict) -> str | None:
        """字辈 for a descendant; None for people who married in."""
        if p["id"] in self.married_in():
            return None
        return self.zibei_for(self.gen[p["id"]])

    # privacy -------------------------------------------------------
    def is_living(self, p: dict) -> bool:
        if "living" in p:
            return bool(p["living"])
        if p.get("death"):
            return False
        b = year(p, "birth")
        if b is not None and b < THIS_YEAR - 110:
            return False
        return True  # unknown → treat as living (privacy first)

    # evidence ------------------------------------------------------
    def status(self, p: dict) -> str:
        if p.get("status") in STATUS_ZH:
            return p["status"]
        srcs = [self.sources[s] for s in p.get("sources", []) if s in self.sources]
        if not srcs:
            return "oral"
        if all(s.get("kind") == "oral" for s in srcs):
            return "oral"
        groups = {s.get("group") or s.get("id") for s in srcs}
        return "corroborated" if len(groups) >= 2 else "single"


def year(p: dict, key: str) -> int | None:
    v = p.get(key)
    if isinstance(v, dict):
        y = v.get("year")
        return y if isinstance(y, int) else None
    return None


def split_name(p: dict) -> tuple[str, str]:
    name = p.get("name", "")
    if p.get("surname"):
        sur = p["surname"]
        given = name[len(sur):] if name.startswith(sur) else name
        return sur, ("" if given == "氏" else given)
    for c in COMPOUND_SURNAMES:
        if name.startswith(c) and len(name) > len(c):
            return c, name[len(c):]
    if name.endswith("氏") and len(name) <= 3:
        return name[:-1], ""
    return (name[:1], name[1:]) if len(name) >= 2 else ("", name)


def years_label(p: dict, living: bool = False) -> str:
    def one(key: str) -> str:
        v = p.get(key)
        if not isinstance(v, dict):
            return "?"
        y = v.get("year")
        if not isinstance(y, int):
            return "?"
        return ("约" if v.get("approx") else "") + str(y)
    b, d = one("birth"), one("death")
    if b == "?" and d == "?":
        return ""
    if living and d == "?":
        return f"{b}–"
    return f"{b}–{d}"


# ------------------------------------------------------------------ check


def check(t: Tree) -> list[Issue]:
    out: list[Issue] = []
    cur = {"pid": ""}
    add = lambda lv, code, who, msg: out.append(Issue(lv, code, who, msg, cur["pid"]))
    nm = lambda pid: t.by_id.get(pid, {}).get("name", pid)

    for d in t.dupe_ids:
        add("error", "dup-id", d, f"id {d} 重复，后一个会覆盖前一个")

    for p in t.people:
        pid, name = p["id"], p.get("name", p["id"])
        cur["pid"] = pid
        who = f"{name}（{pid}）"
        if not p.get("name"):
            add("error", "no-name", pid, "缺少姓名；不知道名字就写“某氏”“佚名”，并在备注里说明")
        for rel in ("father", "mother"):
            r = p.get(rel)
            if r and r not in t.by_id:
                add("error", "bad-ref", who, f"{rel} 指向不存在的 id：{r}")
        for s in p.get("spouses", []) or []:
            if s not in t.by_id:
                add("error", "bad-ref", who, f"spouses 指向不存在的 id：{s}")
        for s in p.get("sources", []) or []:
            if s not in t.sources:
                add("error", "bad-source", who, f"出处 {s} 不在 sources 列表里")
        f, m = t.by_id.get(p.get("father") or ""), t.by_id.get(p.get("mother") or "")
        if f and f.get("sex") == "F":
            add("warn", "sex", who, f"父亲 {nm(f['id'])} 标成了女性")
        if m and m.get("sex") == "M":
            add("warn", "sex", who, f"母亲 {nm(m['id'])} 标成了男性")

        # generation
        g = p.get("generation")
        if isinstance(g, int) and f and isinstance(f.get("generation"), int) and g != f["generation"] + 1:
            add("warn", "generation", who, f"第{g}世，但父亲是第{f['generation']}世；过继、兼祧或抄错时会这样，核对原谱")

        # 字辈
        if p.get("sex") == "M":
            zb = t.zibei_of(p)
            names = [p.get("pu_name") or "", p.get("name") or ""]
            if zb and not any(zb in n[1:] for n in names if n):
                add("info", "zibei", who, f"第{t.gen[pid]}世字辈是“{zb}”，名字里没有；可能另有谱名，或这一支不按字辈取名")

        # dates
        b, dth = year(p, "birth"), year(p, "death")
        if b and dth and dth < b:
            add("error", "dates", who, f"卒年 {dth} 早于生年 {b}")
        if b and dth and dth - b > 110:
            add("warn", "dates", who, f"寿 {dth - b} 岁，检查年号或干支是否换算错了")
        if b and f:
            fb, fd = year(f, "birth"), year(f, "death")
            if fb and b - fb < 14:
                add("warn", "dates", who, f"出生时父亲 {nm(f['id'])} 才 {b - fb} 岁")
            if fb and b - fb > 75:
                add("warn", "dates", who, f"出生时父亲 {nm(f['id'])} 已 {b - fb} 岁，可能是过继或世系接错")
            if fd and b > fd + 1:
                add("warn", "dates", who, f"生于 {b}，父亲 {nm(f['id'])} 卒于 {fd}")
        if b and m:
            mb, md = year(m, "birth"), year(m, "death")
            if mb and not 13 <= b - mb <= 55:
                add("warn", "dates", who, f"出生时母亲 {nm(m['id'])} {b - mb} 岁，可能是继母、嫡母或记错")
            if md and b > md:
                add("warn", "dates", who, f"生于 {b}，母亲 {nm(m['id'])} 卒于 {md}；可能是继母或嫡母")

        # evidence
        st = t.status(p)
        explicit = p.get("status")
        nsrc = len([s for s in p.get("sources", []) if s in t.sources])
        if explicit == "corroborated" and nsrc < 2:
            add("warn", "status", who, "标成“互证”，但只有不到两个出处")
        if st == "oral" and not t.is_living(p):
            add("todo", "unsourced", who, "只有口述或没有出处；找一份书面记录（族谱、墓碑、证件、档案）")
        if b and b < 1368 and not any(t.sources[s].get("kind") == "original"
                                      for s in p.get("sources", []) if s in t.sources):
            add("warn", "remote", who, f"生于 {b} 年，明以前的远祖多为后世修谱时追述，没有同时代原始记录时按“传说”处理")
        if p.get("legend"):
            add("info", "legend", who, "标记为传说或攀附，报告中不能当成事实写")

    cur["pid"] = ""
    # duplicates: same name under the same parent, or same name with no distinguishing data
    seen: dict[tuple, str] = {}
    for p in t.people:
        key = (p.get("name"), p.get("father"), p.get("mother"))
        if p.get("name") and key in seen:
            add("warn", "duplicate", f"{p.get('name')}（{p['id']}）", f"和 {seen[key]} 同名同父母，确认是不是同一个人")
        seen.setdefault(key, p["id"])

    # living people
    living = [p for p in t.people if t.is_living(p)]
    if living:
        add("info", "living", "", f"{len(living)} 人在世或可能在世：" + "、".join(p.get("name", p["id"]) for p in living[:12])
            + ("…" if len(living) > 12 else "") + "。分享前用 --public 隐去")

    # earliest generation: where to look next
    roots = [p for p in t.people if not t.has_parents_in_tree(p) and p.get("sex") != "F"
             and not any(p["id"] in t.spouses(q["id"]) and t.has_parents_in_tree(q) for q in t.people)]
    for r in roots:
        birth = r.get("birth") if isinstance(r.get("birth"), dict) else {}
        if not birth.get("place") and not r.get("origin"):
            add("todo", "origin", f"{r.get('name')}（{r['id']}）", "最早一代缺祖籍地；先问出村名，再按 references/places.md 对到今天的地名")
    return out


def check_report(t: Tree, issues: list[Issue], public: bool = False) -> str:
    if public:
        living = {p["id"] for p in t.people if t.is_living(p)}
        kept = []
        for i in issues:
            if i.pid in living:
                continue
            if i.code == "living":
                i = Issue(i.level, i.code, "", f"{len(living)} 人在世或可能在世，已隐去", i.pid)
            kept.append(i)
        issues = kept
    order = {"error": 0, "warn": 1, "info": 2, "todo": 3}
    icon = {"error": "❌", "warn": "⚠️", "info": "ℹ️", "todo": "🔎"}
    counts = {k: sum(1 for i in issues if i.level == k) for k in order}
    stats: dict[str, int] = {}
    for p in t.people:
        stats[t.status(p)] = stats.get(t.status(p), 0) + 1
    gens = sorted(set(t.gen.values()))
    lines = [f"# {t.title}：检查结果", "",
             f"{len(t.people)} 人，{len(t.sources)} 个出处，"
             + (f"第 {gens[0]}–{gens[-1]} 世" if gens else "") + "。",
             "证据：" + "，".join(f"{STATUS_ZH[k]} {v}" for k, v in sorted(stats.items(), key=lambda x: x[0])),
             f"错误 {counts['error']}，提醒 {counts['warn']}，说明 {counts['info']}，待查 {counts['todo']}。", ""]
    for lv in order:
        rows = [i for i in issues if i.level == lv]
        if not rows:
            continue
        title = {"error": "必须修正", "warn": "需要核对", "info": "说明", "todo": "待查"}[lv]
        lines += [f"## {title}", ""]
        for i in rows:
            lines.append(f"- {icon[lv]} {i.who + '：' if i.who else ''}{i.msg} `[{i.code}]`")
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ svg

BW, BH, SG, HG, ROW, LEFT, TOP = 128, 66, 10, 28, 118, 104, 92
FONT = "'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Noto Sans CJK SC','Source Han Sans SC',sans-serif"
STYLE = {
    "corroborated": ("#1f6f43", "none", 2.2),
    "single": ("#1f6f43", "6 4", 1.6),
    "oral": ("#8a6d3b", "2 4", 1.6),
    "hypothesis": ("#8a6d3b", "2 4", 1.6),
    "contradicted": ("#b42318", "none", 2.2),
}


def layout(t: Tree):
    """Return {pid: (x, y)} for box top-left corners, plus group info and size."""
    married_in = t.married_in()

    def group_of(pid: str) -> list[str]:
        return [pid] + [s for s in t.spouses(pid) if s in married_in]

    def kids_of(pid: str) -> list[str]:
        ids: list[str] = []
        for member in group_of(pid):
            for c in t.children(member):
                if c["id"] not in ids and c["id"] not in married_in:
                    # attach to the father's group first, then the mother's
                    f, m = c.get("father"), c.get("mother")
                    owner = f if f in t.by_id else m
                    if owner in group_of(pid):
                        ids.append(c["id"])
        ids.sort(key=lambda x: (year(t.by_id[x], "birth") or 9999, t.people.index(t.by_id[x])))
        return ids

    widths: dict[str, float] = {}

    def measure(pid: str, stack=()) -> float:
        if pid in stack:
            return BW
        n = len(group_of(pid))
        gw = n * BW + (n - 1) * SG
        ks = kids_of(pid)
        kw = sum(measure(k, stack + (pid,)) for k in ks) + HG * max(0, len(ks) - 1)
        widths[pid] = max(gw, kw)
        return widths[pid]

    roots = [p["id"] for p in t.people if not t.has_parents_in_tree(p) and p["id"] not in married_in]
    min_gen = min(t.gen.values()) if t.gen else 1
    pos: dict[str, tuple[float, float]] = {}
    groups: list[tuple[str, list[str], list[str]]] = []

    def place(pid: str, x0: float, stack=()) -> None:
        if pid in stack:
            return
        members = group_of(pid)
        gw = len(members) * BW + (len(members) - 1) * SG
        w = widths[pid]
        gx = x0 + (w - gw) / 2
        for i, mid in enumerate(members):
            pos[mid] = (gx + i * (BW + SG), TOP + (t.gen[mid] - min_gen) * ROW)
        ks = kids_of(pid)
        kw = sum(widths[k] for k in ks) + HG * max(0, len(ks) - 1)
        cx = x0 + (w - kw) / 2
        for k in ks:
            place(k, cx, stack + (pid,))
            cx += widths[k] + HG
        groups.append((pid, members, ks))

    x = LEFT
    for r in roots:
        measure(r)
        place(r, x)
        x += widths[r] + HG * 2
    # anyone left unplaced (cycles, odd data): put them in a row at the end
    for p in t.people:
        if p["id"] not in pos:
            pos[p["id"]] = (x, TOP + (t.gen[p["id"]] - min_gen) * ROW)
            x += BW + HG
    width = max(x - HG * 2, LEFT + BW) + 40
    max_gen = max(t.gen.values()) if t.gen else min_gen
    height = TOP + (max_gen - min_gen) * ROW + BH + 96
    return pos, groups, width, height, min_gen, max_gen


def svg(t: Tree, public: bool = False) -> str:
    pos, groups, W, H, g0, g1 = layout(t)
    e = lambda s: html.escape(str(s), quote=True)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
         f'viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="{e(t.title)} 世系图">',
         f'<rect width="100%" height="100%" fill="#fbf7ef"/>',
         f'<g font-family="{FONT}">',
         f'<text x="{LEFT}" y="44" font-size="24" font-weight="700" fill="#2b2118">{e(t.title)}</text>']
    sub = t.data.get("subtitle")
    if sub:
        o.append(f'<text x="{LEFT}" y="68" font-size="13" fill="#7a6a58">{e(sub)}</text>')
    # generation rows
    for g in range(g0, g1 + 1):
        y = TOP + (g - g0) * ROW
        o.append(f'<line x1="16" y1="{y + BH / 2:.0f}" x2="{W - 16:.0f}" y2="{y + BH / 2:.0f}" stroke="#efe6d6" stroke-width="1"/>')
        o.append(f'<text x="20" y="{y + 26:.0f}" font-size="13" fill="#7a6a58">第{g}世</text>')
        zb = t.zibei_for(g)
        if zb:
            o.append(f'<text x="20" y="{y + 54:.0f}" font-size="24" font-weight="700" fill="#9b2c1f">{e(zb)}</text>')
    # connectors
    for pid, members, ks in groups:
        if not ks:
            continue
        xs = [pos[m][0] for m in members]
        cx = (min(xs) + max(xs) + BW) / 2
        by = pos[pid][1] + BH
        kxs = [pos[k][0] + BW / 2 for k in ks]
        ky = min(pos[k][1] for k in ks)
        my = by + (ky - by) / 2
        o.append(f'<path d="M{cx:.1f},{by:.1f} V{my:.1f}" stroke="#6b5a48" stroke-width="1.4" fill="none"/>')
        o.append(f'<path d="M{min(kxs + [cx]):.1f},{my:.1f} H{max(kxs + [cx]):.1f}" stroke="#6b5a48" stroke-width="1.4" fill="none"/>')
        for k, kx in zip(ks, kxs):
            o.append(f'<path d="M{kx:.1f},{my:.1f} V{pos[k][1]:.1f}" stroke="#6b5a48" stroke-width="1.4" fill="none"/>')
        if len(members) > 1:
            y = pos[pid][1] + BH / 2
            o.append(f'<path d="M{min(xs) + BW:.1f},{y:.1f} H{max(xs):.1f}" stroke="#9b2c1f" stroke-width="1.4" fill="none"/>')
    # boxes
    for p in t.people:
        x, y = pos[p["id"]]
        hide = public and t.is_living(p)
        st = t.status(p)
        stroke, dash, sw = STYLE.get(st, STYLE["oral"])
        fill = "#fff" if p.get("sex") != "F" else "#fff6f3"
        rx = 6 if p.get("sex") != "F" else 18
        o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{BW}" height="{BH}" rx="{rx}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{sw}"' + (f' stroke-dasharray="{dash}"' if dash != "none" else "") + "/>")
        cx = x + BW / 2
        if hide:
            o.append(f'<text x="{cx:.1f}" y="{y + 38:.1f}" font-size="15" text-anchor="middle" fill="#7a6a58">在世</text>')
            continue
        name = p.get("name", "?")
        if p.get("legend"):
            name += "*"
        o.append(f'<text x="{cx:.1f}" y="{y + 25:.1f}" font-size="17" font-weight="700" text-anchor="middle" fill="#2b2118">{e(name)}</text>')
        line2 = "  ".join(x for x in (
            ("字" + p["zi"]) if p.get("zi") else "", ("号" + p["hao"]) if p.get("hao") else "",
            ("谱名" + p["pu_name"]) if p.get("pu_name") and p.get("pu_name") != p.get("name") else "") if x)
        if not line2 and p.get("alt_names"):
            line2 = str(p["alt_names"][0])
        if line2:
            o.append(f'<text x="{cx:.1f}" y="{y + 43:.1f}" font-size="11.5" text-anchor="middle" fill="#6b5a48">{e(line2[:16])}</text>')
        yl = years_label(p, t.is_living(p))
        if yl:
            o.append(f'<text x="{cx:.1f}" y="{y + 59:.1f}" font-size="11.5" text-anchor="middle" fill="#6b5a48">{e(yl)}</text>')
    # legend
    ly = H - 34
    items = [("corroborated", "两个以上出处互证"), ("single", "单一出处"), ("oral", "口述或无出处"), ("contradicted", "有矛盾")]
    lx = LEFT
    for st, label in items:
        stroke, dash, sw = STYLE[st]
        o.append(f'<rect x="{lx}" y="{ly - 13}" width="26" height="16" rx="3" fill="#fff" stroke="{stroke}" stroke-width="{sw}"'
                 + (f' stroke-dasharray="{dash}"' if dash != "none" else "") + "/>")
        o.append(f'<text x="{lx + 34}" y="{ly}" font-size="12.5" fill="#6b5a48">{label}</text>')
        lx += 34 + 13 * len(label) + 26
    o.append(f'<text x="{lx}" y="{ly}" font-size="12.5" fill="#6b5a48">圆角框为女性　* 传说或存疑</text>')
    o.append("</g></svg>")
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------ gedcom


def gedcom(t: Tree, public: bool = False) -> str:
    ids = {p["id"]: f"@I{i + 1}@" for i, p in enumerate(t.people)}
    fams: dict[tuple, dict] = {}

    def fam(h: str | None, w: str | None) -> dict:
        key = (h, w)
        if key not in fams:
            fams[key] = {"id": f"@F{len(fams) + 1}@", "h": h, "w": w, "c": []}
        return fams[key]

    for p in t.people:
        f, m = p.get("father"), p.get("mother")
        f = f if f in t.by_id else None
        m = m if m in t.by_id else None
        if f or m:
            fam(f, m)["c"].append(p["id"])
    for p in t.people:
        for s in t.spouses(p["id"]):
            a, b = (p["id"], s) if p.get("sex") != "F" else (s, p["id"])
            if (a, b) not in fams:
                fam(a, b)
    lines = ["0 HEAD", "1 SOUR XUNGEN", "2 NAME xungen family.py", "2 VERS 0.1.0", "1 GEDC", "2 VERS 5.5.1",
             "2 FORM LINEAGE-LINKED", "1 CHAR UTF-8", f"1 DATE {_dt.date.today().strftime('%d %b %Y').upper()}"]
    srcs = {sid: f"@S{i + 1}@" for i, sid in enumerate(t.sources)}

    def note(level: int, text: str) -> list[str]:
        parts = str(text).splitlines() or [""]
        out = [f"{level} NOTE {parts[0]}"]
        out += [f"{level + 1} CONT {x}" for x in parts[1:]]
        return out

    for p in t.people:
        hide = public and t.is_living(p)
        sur, given = split_name(p)
        lines.append(f"0 {ids[p['id']]} INDI")
        if hide:
            lines += [f"1 NAME 在世 /{sur}/", "1 RESN privacy"]
        else:
            lines.append(f"1 NAME {given + ' ' if given else ''}/{sur}/")
            lines += ([f"2 GIVN {given}"] if given else []) + ([f"2 SURN {sur}"] if sur else [])
            for alias, label in ((p.get("zi"), "字"), (p.get("hao"), "号"), (p.get("pu_name"), "谱名")):
                if alias:
                    lines += [f"1 NAME {alias}", f"2 TYPE aka", f"2 NOTE {label}"]
            for alt in p.get("alt_names", []) or []:
                lines += [f"1 NAME {alt}", "2 TYPE aka"]
        if p.get("sex") in ("M", "F"):
            lines.append(f"1 SEX {p['sex']}")
        if not hide:
            for key, tag in (("birth", "BIRT"), ("death", "DEAT")):
                ev = p.get(key)
                if isinstance(ev, dict):
                    lines.append(f"1 {tag}")
                    if isinstance(ev.get("year"), int):
                        lines.append(f"2 DATE {'ABT ' if ev.get('approx') else ''}{ev['year']}")
                    if ev.get("place"):
                        lines.append(f"2 PLAC {ev['place']}")
                    if ev.get("text"):
                        lines += note(2, f"原始记载：{ev['text']}")
            g = t.gen.get(p["id"])
            zb = t.zibei_of(p)
            lines += note(1, f"第{g}世" + (f"，字辈“{zb}”" if zb else "") + f"；证据：{STATUS_ZH[t.status(p)]}")
            if p.get("notes"):
                lines += note(1, p["notes"])
            for s in p.get("sources", []) or []:
                if s in srcs:
                    lines.append(f"1 SOUR {srcs[s]}")
        for f in fams.values():
            if p["id"] in f["c"]:
                lines.append(f"1 FAMC {f['id']}")
            if p["id"] in (f["h"], f["w"]):
                lines.append(f"1 FAMS {f['id']}")
    for f in fams.values():
        lines.append(f"0 {f['id']} FAM")
        if f["h"]:
            lines.append(f"1 HUSB {ids[f['h']]}")
        if f["w"]:
            lines.append(f"1 WIFE {ids[f['w']]}")
        for c in f["c"]:
            lines.append(f"1 CHIL {ids[c]}")
    for sid, gid in srcs.items():
        s = t.sources[sid]
        lines += [f"0 {gid} SOUR", f"1 TITL {s.get('title', sid)}"]
        if s.get("where"):
            lines.append(f"1 REPO")
            lines.append(f"2 NAME {s['where']}")
        if s.get("detail") or s.get("kind"):
            lines += note(1, "；".join(x for x in (s.get("kind", ""), s.get("detail", "")) if x))
    lines.append("0 TRLR")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ table


def table(t: Tree, public: bool = False) -> str:
    nm = lambda pid: t.by_id[pid]["name"] if pid in t.by_id and not (public and t.is_living(t.by_id[pid])) else ("在世" if pid in t.by_id else "")
    rows = sorted(t.people, key=lambda p: (t.gen[p["id"]], year(p, "birth") or 9999, t.people.index(p)))
    out = [f"# {t.title}：世系表", "", "| 世 | 字辈 | 姓名 | 字 / 号 | 父 | 母 | 配偶 | 生卒 | 出处 | 证据 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for p in rows:
        g = t.gen[p["id"]]
        hide = public and t.is_living(p)
        zh = "、".join(x for x in (("字" + p["zi"]) if p.get("zi") else "", ("号" + p["hao"]) if p.get("hao") else "") if x)
        srcs = "、".join(t.sources[s].get("short") or t.sources[s].get("title", s) for s in p.get("sources", []) if s in t.sources)
        out.append("| " + " | ".join([
            str(g), t.zibei_of(p) or "", "在世" if hide else p.get("name", "") + ("*" if p.get("legend") else ""),
            "" if hide else zh, nm(p.get("father") or ""), nm(p.get("mother") or ""),
            "、".join(nm(s) for s in t.spouses(p["id"])), "" if hide else years_label(p, t.is_living(p)),
            "" if hide else srcs, STATUS_ZH[t.status(p)]]) + " |")
    out += ["", "\\* 传说或存疑，不能当成事实引用。"]
    if t.sources:
        out += ["", "## 出处", ""]
        for sid, s in t.sources.items():
            kind = {"original": "原始记录", "derivative": "转录/后修", "oral": "口述", "index": "索引"}.get(s.get("kind", ""), s.get("kind", ""))
            out.append(f"- **{sid}** {s.get('title', '')}" + (f"（{kind}）" if kind else "")
                       + (f"，{s['where']}" if s.get("where") else "") + (f"，{s['detail']}" if s.get("detail") else ""))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ cli


def load(path: str) -> Tree:
    with open(path, encoding="utf-8") as fh:
        return Tree(json.load(fh))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="寻根：检查、绘制、导出家族世系 JSON")
    ap.add_argument("command", choices=["check", "svg", "gedcom", "table", "all"])
    ap.add_argument("file")
    ap.add_argument("-o", "--out", help="输出文件；all 命令时为输出目录")
    ap.add_argument("--public", action="store_true", help="隐去在世或可能在世的人")
    a = ap.parse_args(argv)
    t = load(a.file)
    issues = check(t)
    if a.command == "check":
        rep = check_report(t, issues, a.public)
        if a.out:
            Path(a.out).write_text(rep, encoding="utf-8")
        else:
            print(rep)
        return 1 if any(i.level == "error" for i in issues) else 0
    makers = {"svg": (svg, "tree.svg"), "gedcom": (gedcom, "family.ged"), "table": (table, "tree.md")}
    if a.command == "all":
        outdir = Path(a.out or ".")
        outdir.mkdir(parents=True, exist_ok=True)
        for fn, fname in makers.values():
            (outdir / fname).write_text(fn(t, a.public), encoding="utf-8")
        (outdir / "check.md").write_text(check_report(t, issues, a.public), encoding="utf-8")
        print(f"写入 {outdir}/: tree.svg family.ged tree.md check.md")
        return 0
    fn, default = makers[a.command]
    text = fn(t, a.public)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    errs = [i for i in issues if i.level == "error"]
    if errs:
        print(f"注意：数据里有 {len(errs)} 个错误，先运行 check 查看", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
