import json
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "xungen" / "scripts"
EXAMPLE = ROOT / "skills" / "xungen" / "assets" / "family.example.json"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


when = load("when")
family = load("family")


class WhenTests(unittest.TestCase):
    def years(self, text, **kw):
        return when.convert(text, **kw)["years"]

    def test_reign_eras(self):
        self.assertEqual(self.years("光绪二十六年三月初五"), [1900])
        self.assertEqual(self.years("光緒廿六年"), [1900])
        self.assertEqual(self.years("康熙元年"), [1662])
        self.assertEqual(self.years("乾隆六十年"), [1795])
        self.assertEqual(self.years("万历四十八年"), [1620])
        self.assertEqual(self.years("崇祯十七年"), [1644])
        self.assertEqual(self.years("永历三十七年"), [1683])

    def test_republic_japan_manchukuo(self):
        self.assertEqual(self.years("民国三十八年"), [1949])
        self.assertEqual(self.years("民國115年"), [2026])
        self.assertEqual(self.years("昭和5年"), [1930])
        self.assertEqual(self.years("明治二十八年"), [1895])
        self.assertEqual(self.years("康德元年"), [1934])

    def test_ganzhi(self):
        self.assertEqual(when.ganzhi(1900), "庚子")
        self.assertEqual(when.ganzhi(1984), "甲子")
        self.assertEqual(when.ganzhi(2026), "丙午")
        self.assertEqual(self.years("道光庚子"), [1840])
        self.assertEqual(self.years("庚子年", lo=1800, hi=1950), [1840, 1900])

    def test_ganzhi_conflict_is_reported(self):
        r = when.convert("光绪二十六年岁次辛丑")
        self.assertEqual(r["years"], [1900])
        self.assertTrue(any("矛盾" in n for n in r["notes"]))

    def test_era_used_past_its_end(self):
        r = when.convert("宣统四年")
        self.assertEqual(r["years"], [1912])
        self.assertTrue(any("超出" in n for n in r["notes"]))

    def test_late_lunar_month_may_be_next_year(self):
        r = when.convert("光绪二十六年腊月")
        self.assertEqual(r["lunar_month"], 12)
        self.assertTrue(any("1901" in n for n in r["notes"]))

    def test_xusui_and_zodiac(self):
        self.assertEqual(self.years("虚岁73", ref=2026), [1954])
        self.assertEqual(self.years("属虎", ref=2026, age=80, lo=1900, hi=2026), [1938, 1950, 1962])

    def test_errors(self):
        self.assertIn("error", when.convert("洪武"))
        self.assertIn("error", when.convert("随便写点"))

    def test_cli(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "when.py"), "民国三十八年", "--json"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["years"], [1949])


class FamilyTests(unittest.TestCase):
    def tree(self, data=None):
        if data is None:
            data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        return family.Tree(data)

    def codes(self, t):
        return [(i.level, i.code) for i in family.check(t)]

    def test_example_has_no_errors(self):
        t = self.tree()
        self.assertFalse([c for c in self.codes(t) if c[0] == "error"])
        self.assertIn(("info", "zibei"), self.codes(t))  # 陈嘉文 does not use 家

    def test_status(self):
        t = self.tree()
        self.assertEqual(t.status(t.by_id["p1"]), "corroborated")
        self.assertEqual(t.status(t.by_id["p4"]), "single")
        self.assertEqual(t.status(t.by_id["p0"]), "oral")

    def test_living_detection(self):
        t = self.tree()
        self.assertTrue(t.is_living(t.by_id["p13"]))
        self.assertFalse(t.is_living(t.by_id["p1"]))
        self.assertFalse(t.is_living({"id": "x", "birth": {"year": 1850}}))
        self.assertTrue(t.is_living({"id": "x"}))  # unknown → treat as living

    def test_married_in_spouses_have_no_zibei(self):
        t = self.tree()
        self.assertIsNone(t.zibei_of(t.by_id["p2"]))
        self.assertEqual(t.zibei_of(t.by_id["p1"]), "德")

    def test_bad_references_and_dates(self):
        t = self.tree({"people": [
            {"id": "a", "name": "王大", "sex": "M", "birth": {"year": 1900}, "death": {"year": 1890}},
            {"id": "b", "name": "王二", "sex": "M", "father": "a", "birth": {"year": 1905}},
            {"id": "c", "name": "王三", "sex": "M", "father": "zz", "sources": ["nope"]},
        ], "sources": []})
        codes = self.codes(t)
        self.assertIn(("error", "dates"), codes)
        self.assertIn(("error", "bad-ref"), codes)
        self.assertIn(("error", "bad-source"), codes)
        self.assertIn(("warn", "dates"), codes)  # father aged 5

    def test_remote_ancestor_warning(self):
        t = self.tree({"people": [{"id": "a", "name": "李始祖", "sex": "M", "birth": {"year": 1100},
                                   "death": {"year": 1170}, "sources": ["s"]}],
                       "sources": [{"id": "s", "title": "民国族谱", "kind": "derivative"}]})
        self.assertIn(("warn", "remote"), self.codes(t))

    def test_public_svg_hides_living_names(self):
        t = self.tree()
        private, public = family.svg(t), family.svg(t, public=True)
        self.assertIn("陈远航", private)
        self.assertNotIn("陈远航", public)
        self.assertIn("陈德昌", public)
        import xml.dom.minidom
        xml.dom.minidom.parseString(public)

    def test_public_check_report_hides_living(self):
        t = self.tree()
        rep = family.check_report(t, family.check(t), public=True)
        self.assertNotIn("陈远航", rep)
        self.assertIn("已隐去", rep)

    def test_gedcom(self):
        t = self.tree()
        g = family.gedcom(t)
        self.assertTrue(g.startswith("0 HEAD"))
        self.assertTrue(g.rstrip().endswith("0 TRLR"))
        self.assertIn("1 NAME 德昌 /陈/", g)
        self.assertIn("1 NAME /黄/", g)
        self.assertIn("2 DATE ABT 1845", g)
        self.assertEqual(g.count(" INDI"), len(t.people))
        pub = family.gedcom(t, public=True)
        self.assertNotIn("远航", pub)

    def test_compound_surname(self):
        self.assertEqual(family.split_name({"name": "欧阳修"}), ("欧阳", "修"))
        self.assertEqual(family.split_name({"name": "李氏", "surname": "李"}), ("李", ""))

    def test_cli_all(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(SCRIPTS / "family.py"), "all", str(EXAMPLE), "-o", d, "--public"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            for f in ("tree.svg", "family.ged", "tree.md", "check.md"):
                self.assertTrue((Path(d) / f).stat().st_size > 100)
            self.assertNotIn("陈远航", (Path(d) / "tree.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
