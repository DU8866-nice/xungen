#!/usr/bin/env python3
"""Convert dates found in Chinese family records to Gregorian years.

Handles reign eras (明、南明、后金/清), 民国, Japanese eras used in Taiwan
records, 满洲国, sexagenary (干支) years, zodiac animals and 虚岁 ages.
It works at year level. For an exact day, look the date up in Academia
Sinica's 两千年中西历转换 (sinocal.sinica.edu.tw) or, from 1901 on, the
Hong Kong Observatory conversion tables.

Usage:
  when.py 光绪二十六年三月初五
  when.py 道光庚子
  when.py 庚子年 --from 1800 --to 1950
  when.py 虚岁73 --ref 2026
  when.py 属虎 --age 80 --ref 2026
  when.py 民国三十八年 --json

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"

# era: (first Gregorian year of 元年, last year in official use, dynasty label)
# The Gregorian year is the one in which most of that lunar year falls.
ERAS: dict[str, tuple[int, int, str]] = {
    # 明
    "洪武": (1368, 1398, "明"), "建文": (1399, 1402, "明"), "永乐": (1403, 1424, "明"),
    "洪熙": (1425, 1425, "明"), "宣德": (1426, 1435, "明"), "正统": (1436, 1449, "明"),
    "景泰": (1450, 1457, "明"), "天顺": (1457, 1464, "明"), "成化": (1465, 1487, "明"),
    "弘治": (1488, 1505, "明"), "正德": (1506, 1521, "明"), "嘉靖": (1522, 1566, "明"),
    "隆庆": (1567, 1572, "明"), "万历": (1573, 1620, "明"), "泰昌": (1620, 1620, "明"),
    "天启": (1621, 1627, "明"), "崇祯": (1628, 1644, "明"),
    # 南明（明郑在台湾沿用永历到 1683 年）
    "弘光": (1645, 1645, "南明"), "隆武": (1645, 1646, "南明"), "永历": (1647, 1683, "南明/明郑"),
    # 后金、清
    "天命": (1616, 1626, "后金"), "天聪": (1627, 1636, "后金"), "崇德": (1636, 1643, "清"),
    "顺治": (1644, 1661, "清"), "康熙": (1662, 1722, "清"), "雍正": (1723, 1735, "清"),
    "乾隆": (1736, 1795, "清"), "嘉庆": (1796, 1820, "清"), "道光": (1821, 1850, "清"),
    "咸丰": (1851, 1861, "清"), "同治": (1862, 1874, "清"), "光绪": (1875, 1908, "清"),
    "宣统": (1909, 1911, "清"),
    # 民国（台湾沿用至今）
    "民国": (1912, 9999, "中华民国"),
    # 满洲国
    "大同": (1932, 1934, "满洲国"), "康德": (1934, 1945, "满洲国"),
    # 日本年号（台湾日治时期户籍等）
    "明治": (1868, 1912, "日本"), "大正": (1912, 1926, "日本"), "昭和": (1926, 1989, "日本"),
    "平成": (1989, 2019, "日本"), "令和": (2019, 9999, "日本"),
}

TRAD = str.maketrans({
    "緒": "绪", "豐": "丰", "慶": "庆", "順": "顺", "統": "统", "國": "国", "萬": "万",
    "曆": "历", "歷": "历", "禎": "祯", "啟": "启", "樂": "乐", "聰": "聪", "龍": "龙",
    "馬": "马", "雞": "鸡", "豬": "猪", "歲": "岁", "閏": "闰", "臘": "腊", "壽": "寿",
    "啓": "启", "隆": "隆", "於": "于", "虛": "虚", "屬": "属", "貳": "二", "叁": "三",
    "參": "三", "肆": "四", "伍": "五", "陸": "六", "柒": "七", "捌": "八", "玖": "九",
    "拾": "十", "壹": "一",
})

DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}


def cn_number(s: str) -> int | None:
    """Parse 元, 一..九十九, 一百一十五, 廿/卅/卌, Arabic and full-width digits."""
    s = s.strip().translate(TRAD)
    if not s:
        return None
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    if s in ("元", "正"):
        return 1
    s = s.replace("廿", "二十").replace("卅", "三十").replace("卌", "四十")
    total, num = 0, 0
    for ch in s:
        if ch in DIGITS:
            num = DIGITS[ch]
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
        elif ch == "百":
            total += (num or 1) * 100
            num = 0
        else:
            return None
    return total + num


def ganzhi(year: int) -> str:
    i = (year - 4) % 60
    return STEMS[i % 10] + BRANCHES[i % 12]


def zodiac(year: int) -> str:
    return ZODIAC[(year - 4) % 12]


def years_for_ganzhi(gz: str, lo: int, hi: int) -> list[int]:
    return [y for y in range(lo, hi + 1) if ganzhi(y) == gz]


EXACT_DAY = ("精确到日：中研院两千年中西历转换 https://sinocal.sinica.edu.tw/ ；"
             "1901 年以后也可查香港天文台公历农历对照表 https://www.hko.gov.hk/sc/gts/time/conversion.htm")

ERA_RE = re.compile(r"(" + "|".join(sorted(ERAS, key=len, reverse=True)) + r")\s*"
                    r"(?:([元正一二三四五六七八九十廿卅卌百〇零两0-9０-９]+)\s*年)?\s*"
                    r"(?:岁次)?\s*([" + STEMS + r"][" + BRANCHES + r"])?")
MONTH_RE = re.compile(r"(闰)?\s*([正一二三四五六七八九十冬腊]+|[0-9]{1,2})\s*月")
GZ_RE = re.compile(r"([" + STEMS + r"][" + BRANCHES + r"])\s*年?")
XUSUI_RE = re.compile(r"虚岁\s*([0-9一二三四五六七八九十百]+)")
SHU_RE = re.compile(r"属\s*([" + ZODIAC + r"])")


def month_number(m: str) -> int | None:
    m = m.replace("冬", "十一").replace("腊", "十二")
    return cn_number(m)


def convert(text: str, ref: int | None = None, lo: int = 1368, hi: int | None = None,
            age: int | None = None) -> dict:
    """Return a dict describing the Gregorian year(s) for one Chinese date expression."""
    this_year = _dt.date.today().year
    ref = ref or this_year
    hi = hi or this_year
    raw = text
    t = text.translate(TRAD).replace(" ", "")
    out: dict = {"input": raw, "years": [], "notes": []}

    m = ERA_RE.search(t)
    if m:
        era, num, gz = m.group(1), m.group(2), m.group(3)
        start, end, dyn = ERAS[era]
        out["era"] = era
        out["dynasty"] = dyn
        if num:
            n = cn_number(num)
            if n is None or n < 1:
                out["error"] = f"看不懂年数：{num}"
                return out
            y = start + n - 1
            out["years"] = [y]
            if y > end and end != 9999:
                out["notes"].append(f"{era}实际只用到 {end} 年，{era}{num}年超出了正式使用范围；"
                                    "遗老、偏远地区或海外有时继续沿用旧年号，按顺推计算。")
            if gz and ganzhi(y) != gz:
                out["notes"].append(f"记载的干支是{gz}，但 {y} 年是{ganzhi(y)}，两者矛盾，"
                                    "要么年数抄错，要么干支抄错，回原件核对。")
        elif gz:
            lo_e, hi_e = start, (end if end != 9999 else hi)
            ys = years_for_ganzhi(gz, lo_e, hi_e)
            out["years"] = ys
            if not ys:
                out["error"] = f"{era}（{start}–{end}）期间没有{gz}年"
                return out
        else:
            out["error"] = f"只有年号{era}，缺少第几年"
            return out
    else:
        xm = XUSUI_RE.search(t)
        sm = SHU_RE.search(t)
        gm = GZ_RE.search(t)
        if xm:
            n = cn_number(xm.group(1))
            if not n:
                out["error"] = "看不懂虚岁数字"
                return out
            y = ref - n + 1
            out["years"] = [y]
            out["notes"].append(f"虚岁按农历年计：出生当年算 1 岁，每过一个春节加 1 岁。"
                                f"{ref} 年虚岁 {n}，出生的农历年是 {y} 年；"
                                f"如果生在农历年底（公历 1–2 月），公历年份可能是 {y + 1}。")
        elif sm:
            animal = sm.group(1)
            idx = ZODIAC.index(animal)
            cands = [y for y in range(lo, hi + 1) if (y - 4) % 12 == idx]
            if age is not None:
                target = ref - age
                cands = sorted(cands, key=lambda y: abs(y - target))[:3]
                cands.sort()
            out["years"] = cands
            out["notes"].append("生肖按农历年算，春节前出生的人属上一年的生肖。")
        elif gm:
            out["years"] = years_for_ganzhi(gm.group(1), lo, hi)
            out["notes"].append(f"干支 60 年一轮，只有干支时要靠年龄、辈分或事件把范围缩小（当前范围 {lo}–{hi}）。")
        else:
            out["error"] = "没认出年号、干支、生肖或虚岁"
            return out

    mm = MONTH_RE.search(t[m.end():] if m else t)
    if mm and out["years"]:
        mo = month_number(mm.group(2))
        if mo:
            out["lunar_month"] = mo
            out["leap_month"] = bool(mm.group(1))
            if mo >= 11:
                out["notes"].append(f"农历{mo}月可能已进入下一个公历年（{out['years'][0] + 1} 年 1–2 月），"
                                    "精确日期要查对照表。")
    out["ganzhi"] = {str(y): ganzhi(y) for y in out["years"][:12]}
    out["exact_day"] = EXACT_DAY
    return out


def describe(r: dict) -> str:
    if "error" in r:
        return f"{r['input']}：{r['error']}"
    ys = r["years"]
    head = r["input"] + " → "
    if len(ys) == 1:
        y = ys[0]
        head += f"{y} 年（{ganzhi(y)}，属{zodiac(y)}）"
    else:
        head += "可能是 " + "、".join(f"{y}（{ganzhi(y)}）" for y in ys[:12])
        if len(ys) > 12:
            head += f" 等 {len(ys)} 个年份"
    if r.get("dynasty"):
        head += f"  [{r['dynasty']}·{r['era']}]"
    lines = [head] + ["  - " + n for n in r["notes"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="中文纪年 → 公历年份")
    ap.add_argument("text", nargs="+", help="例如：光绪二十六年三月初五、道光庚子、虚岁73、属虎")
    ap.add_argument("--ref", type=int, help="虚岁、年龄对应的参考年份，默认今年")
    ap.add_argument("--age", type=int, help="和“属X”一起用：大约年龄")
    ap.add_argument("--from", dest="lo", type=int, default=1368, help="只有干支或生肖时的搜索起点")
    ap.add_argument("--to", dest="hi", type=int, help="搜索终点，默认今年")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    results = [convert(t, ref=a.ref, lo=a.lo, hi=a.hi, age=a.age) for t in a.text]
    if a.json:
        print(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=2))
    else:
        print("\n".join(describe(r) for r in results))
        if any("error" not in r for r in results):
            print("\n" + EXACT_DAY)
    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
