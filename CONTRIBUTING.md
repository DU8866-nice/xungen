# 参与

欢迎补充。最有用的几类：

1. **查询经验**：某地档案馆、图书馆、宗亲会怎么查家谱，要带什么证件，能不能远程申请。写进 `skills/xungen/references/sources-china.md` 对应的小节，注明核对日期和你看过的页面。
2. **海外华人档案**：还没覆盖的国家和地区（菲律宾、印尼、泰国、越南、秘鲁、古巴等）。按 `sources-overseas.md` 的格式写：资料名称、能查到什么、入口链接。
3. **纪年和地名**：`when.py` 认不出的写法，海外档案里常见的县名、村名拼法。附一个例子，最好加一条测试。
4. **脚本问题**：附上出问题的 `family.json` 片段（把真实姓名换掉）和期望的结果。

提交前运行测试：

```bash
python3 -m unittest discover -s tests -v
```

脚本只用 Python 标准库。示例里不要放真实在世者的信息。

English issues and pull requests are welcome too.
