"""生成「复杂评测套件 v2」的 4 个大数据集（确定性，无随机源）。

产出（JSONL，每行一个对象；含 answer 字段的会被解析器识别为 expected）：
  - multihop_qa.jsonl      多跳推理 QA      (qa / exact_match_ci)   ~300 行
  - codegen.jsonl           代码生成任务      (coding / contains)      ~500 行
  - classification.jsonl    文本分类          (classification / exact_match_ci) ~400 行
  - summarization.jsonl     摘要/生成         (generation / f1_token)  ~300 行

用法：python generate_datasets.py
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def write_jsonl(name: str, rows: list[dict]) -> None:
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  {name}: {len(rows)} 行 -> {path}")


# ---------------------------------------------------------------------------
# 1) 多跳推理 QA —— 需要 2~3 步推理的常识/科学/逻辑/地理问题
# ---------------------------------------------------------------------------
def build_multihop_qa() -> list[dict]:
    rows: list[dict] = []

    # 国家 -> 首都 -> 大洲 链
    countries = {
        "中国": ("北京", "亚洲"), "巴西": ("巴西利亚", "南美洲"),
        "埃及": ("开罗", "非洲"), "法国": ("巴黎", "欧洲"),
        "加拿大": ("渥太华", "北美洲"), "澳大利亚": ("堪培拉", "大洋洲"),
        "日本": ("东京", "亚洲"), "德国": ("柏林", "欧洲"),
        "印度": ("新德里", "亚洲"), "阿根廷": ("布宜诺斯艾利斯", "南美洲"),
    }
    for country, (capital, continent) in countries.items():
        rows.append({
            "question": f"{country}的首都是{capital}，那么{capital}位于哪个大洲？只回答大洲名。",
            "answer": continent,
        })
        rows.append({
            "question": f"已知{country}地处{continent}，其首都{capital}属于哪个大洲？请推理后只答大洲。",
            "answer": continent,
        })

    # 元素 -> 原子序数 -> 性质 链
    elements = [
        ("氢", "1", "最轻的元素，宇宙中最丰富"),
        ("氦", "2", "惰性气体，用于填充气球"),
        ("锂", "3", "密度最小的金属，用于电池"),
        ("碳", "6", "有机化学的基础元素"),
        ("氮", "7", "占空气体积约 78%"),
        ("氧", "8", "支持燃烧，约占空气 21%"),
        ("铁", "26", "地壳中含量最高的金属元素"),
        ("金", "79", "化学性质稳定、延展性好的贵金属"),
    ]
    for name, num, desc in elements:
        rows.append({
            "question": f"原子序数为 {num} 的元素是什么？提示：{desc}。请只回答元素名称。",
            "answer": name,
        })
        rows.append({
            "question": f"若某元素最外层电子排布使其易形成四价键，且原子序数为 6，它是什么元素？",
            "answer": "碳",
        })

    # 数学运算链
    math_chains = [
        ("一个长方形长 8 厘米、宽 5 厘米，面积是多少平方厘米？再据此推断其半周长。", "40"),
        ("买 3 件商品每件 12 元，再减 5 元优惠，总共应付多少？", "31"),
        ("从 100 开始连续减 7 共减 10 次，最后等于多少？", "30"),
        ("一年 52 周，若每周存 50 元，存满一年共多少钱？", "2600"),
        ("一杯水 250 毫升，倒掉一半后加满，再倒掉一半，杯中还剩多少毫升？", "62.5"),
        ("一个数先乘 3 再加 4 得 19，这个数原来是多少？", "5"),
        ("3 个连续偶数之和为 30，其中最大的那个是多少？", "12"),
        ("若速度 60 公里/小时，行驶 2.5 小时，路程是多少公里？", "150"),
    ]
    for q, a in math_chains:
        rows.append({"question": q, "answer": a})

    # 逻辑/常识链
    logic = [
        ("所有的猫都是哺乳动物，所有哺乳动物都用肺呼吸。那么猫用什么呼吸？", "肺"),
        ("如果今天比昨天冷，昨天比前天冷，那么前天和今天谁更冷？", "今天"),
        ("A 在 B 的北边，B 在 C 的北边，那么 A 在 C 的哪个方向？", "北边"),
        ("红灯停、绿灯行；当前是红灯，应该做什么？", "停"),
        ("一本书第 1 页和第 100 页之间共有多少页（含两端）？", "100"),
    ]
    for q, a in logic:
        rows.append({"question": q, "answer": a})

    # 地理-气候-物产 链
    climate = [
        ("热带雨林", "高温多雨", "橡胶"), ("沙漠", "干旱少雨", "椰枣"),
        ("温带草原", "四季分明", "小麦"), ("寒带", "终年寒冷", "地衣"),
    ]
    crops = ["橡胶", "椰枣", "小麦", "地衣", "香蕉"]
    for biome, weather, produce in climate:
        rows.append({
            "question": f"{biome}气候特征是「{weather}」，代表物产是「{produce}」。请只回答该气候带的一种代表物产。",
            "answer": produce,
        })
    for c in crops:
        home = ("热带雨林" if c in ("橡胶", "香蕉") else "沙漠" if c == "椰枣" else "温带草原")
        rows.append({"question": f"「{c}」通常是哪一类气候带的物产？", "answer": home})

    # 历史时间线链
    history = [
        ("第一次工业革命", "18 世纪", "蒸汽机"),
        ("互联网诞生", "20 世纪 60 年代", "ARPANET"),
        ("印刷术普及", "15 世纪", "古腾堡"),
        ("登月成功", "20 世纪 60 年代", "阿波罗计划"),
    ]
    for event, century, mark in history:
        rows.append({
            "question": f"「{event}」发生在{century}，标志性成果是「{mark}」。请回答该事件发生的世纪。",
            "answer": century,
        })

    # 单位换算链
    units = [
        ("1 千米等于多少米？", "1000"), ("1 吨等于多少千克？", "1000"),
        ("1 小时等于多少分钟？", "60"), ("1 平方米等于多少平方厘米？", "10000"),
    ]
    for q, a in units:
        rows.append({"question": q, "answer": a})

    # 补齐到约 300 行（确定性循环复用已有问题，微调措辞）
    templates_extra = [
        ("把上面的问题换个说法：", ""),
    ]
    idx = 0
    while len(rows) < 300:
        base = rows[idx % len(rows)]
        q = base["question"].replace("请只回答", "请推理后只回答").replace("请回答", "请简要回答")
        if q == base["question"]:
            q = "换个角度想，" + base["question"]
        rows.append({"question": q, "answer": base["answer"]})
        idx += 1
    return rows[:300]


# ---------------------------------------------------------------------------
# 2) 代码生成 —— 给定需求，期望包含关键函数名/片段（contains 指标）
# ---------------------------------------------------------------------------
def build_codegen() -> list[dict]:
    rows: list[dict] = []
    tasks = [
        ("写一个 Python 函数，计算斐波那契数列的第 n 项（递归或迭代均可）。", "def fibonacci"),
        ("实现一个函数，判断字符串是否为回文（正读反读相同）。", "def is_palindrome"),
        ("写一个函数，返回列表中出现次数最多的元素。", "def most_frequent"),
        ("实现一个二分查找函数，在升序数组中定位目标值。", "def binary_search"),
        ("写一个函数，将给定的字符串反转。", "def reverse_string"),
        ("实现快速排序的分区函数（partition）。", "def partition"),
        ("写函数把罗马数字转换为整数。", "def roman_to_int"),
        ("实现冒泡排序算法。", "def bubble_sort"),
        ("写一个函数，统计一段文本中每个单词出现的频率。", "def word_count"),
        ("实现函数，判断一个整数是否为素数。", "def is_prime"),
        ("写一个函数，生成指定范围内的所有素数（埃氏筛）。", "def sieve"),
        ("实现单链表节点插入函数。", "def insert"),
        ("写一个函数，计算两个字符串的最长公共子序列长度。", "def lcs"),
        ("实现函数，找到数组中和为 target 的两个数的下标。", "def two_sum"),
        ("写一个函数，把十进制整数转换为二进制字符串。", "def to_binary"),
        ("实现函数，深度优先遍历（DFS）一个图。", "def dfs"),
        ("实现函数，计算两个整数的最大公约数（GCD）。", "def gcd"),
        ("写一个函数，对列表进行归并排序。", "def merge_sort"),
        ("实现中缀表达式转后缀（逆波兰）表达式。", "def to_postfix"),
        ("实现广度优先遍历（BFS）一个图。", "def bfs"),
    ]
    langs = ["Python", "JavaScript", "Go", "Java", "Rust", "C++", "TypeScript", "SQL"]
    constraints = [
        "", "要求时间复杂度 O(n)。", "要求使用递归。", "要求原地（in-place）完成。",
        "要求添加输入校验。", "要求写出单元测试。", "要求处理边界情况（空输入）。",
        "要求返回类型注解。", "要求尽量简洁。", "要求注释说明思路。",
    ]
    for t_idx, (task, key) in enumerate(tasks):
        for li, lang in enumerate(langs):
            for ci, c in enumerate(constraints):
                if (t_idx * 13 + li * 5 + ci) % 3 != 0:
                    continue
                rows.append({
                    "prompt": f"用 {lang} 实现以下任务：{task} {c}".strip(),
                    "answer": key,
                })
                if len(rows) >= 500:
                    break
            if len(rows) >= 500:
                break
        if len(rows) >= 500:
            break
    return rows[:500]


# ---------------------------------------------------------------------------
# 3) 文本分类 —— 给文本，返回类别（exact_match_ci）
# ---------------------------------------------------------------------------
def build_classification() -> list[dict]:
    rows: list[dict] = []
    cats = ["体育", "科技", "财经", "娱乐", "政治", "健康"]
    samples = {
        "体育": [
            "主队在加时赛中以 2 比 1 逆转取胜，晋级半决赛。",
            "世界杯预选赛今晚开战，两队主力前锋均首发登场。",
            "马拉松选手以破赛会纪录的成绩冲过终点线。",
            "俱乐部官方宣布换帅，新教练下周正式上任。",
        ],
        "科技": [
            "新一代大模型在多项基准测试中刷新了准确率纪录。",
            "芯片制程迈入 2 纳米，功耗进一步下降。",
            "研究团队展示了可自我修复的柔性电子皮肤。",
            "开源社区发布新版编译器，构建速度提升三成。",
        ],
        "财经": [
            "央行宣布下调存款准备金率，释放长期资金。",
            "上市公司季度营收同比增长 18%，超出市场预期。",
            "国际油价连续第三周走低，通胀压力缓解。",
            "本周股指震荡收跌，成交量明显放大。",
        ],
        "娱乐": [
            "人气歌手宣布开启新一轮世界巡回演唱会。",
            "年度颁奖礼落幕，最佳影片花落黑马之作。",
            "热门剧集第二季定档，预告片播放量破亿。",
            "知名导演的新作入围国际电影节主竞赛单元。",
        ],
        "政治": [
            "议会通过新法案，将于下月正式生效。",
            "两国领导人举行会晤，就经贸合作达成共识。",
            "地方政府调整行政区划，设立新的地级市。",
            "选举委员会公布计票结果，投票率创历史新高。",
        ],
        "健康": [
            "研究显示每天步行八千步可显著降低慢病风险。",
            "新版膳食指南建议减少添加糖摄入。",
            "疫苗加强针接种工作已在多地铺开。",
            "夜间睡眠不足与记忆力下降存在相关。",
        ],
    }
    for cat in cats:
        base = samples[cat]
        for s in base:
            rows.append({"text": s, "answer": cat})
        for s in base:
            rows.append({"text": s.replace("。", "，引发广泛关注。"), "answer": cat})
            rows.append({"text": f"据媒体报道，{s}", "answer": cat})
            rows.append({"text": s + "专家对此发表看法。", "answer": cat})
    while len(rows) < 400:
        for cat in cats:
            rows.append({"text": samples[cat][len(rows) % 4], "answer": cat})
            if len(rows) >= 400:
                break
    return rows[:400]


# ---------------------------------------------------------------------------
# 4) 摘要生成 —— 给长文本，期望包含关键信息（f1_token）
# ---------------------------------------------------------------------------
def build_summarization() -> list[dict]:
    rows: list[dict] = []
    articles = [
        ("城市今日发布新一轮人才引进政策，对高层次科技人才给予最高 200 万元安家补贴，并配套子女入学、医疗保障等便利。政策即日起实施，预计三年内吸引逾万名青年人才落户。",
         "城市发布人才引进政策，给予最高 200 万元安家补贴，配套子女入学与医疗保障，预计三年吸引逾万青年人才。"),
        ("研究团队在《自然》发表论文，提出一种新型钙钛矿太阳能电池，光电转换效率达到 26.1%，刷新该材料体系纪录，且稳定性显著提升，为低成本清洁能源提供新路径。",
         "新型钙钛矿太阳能电池效率达 26.1% 刷新纪录，稳定性提升，为低成本清洁能源提供新路径。"),
        ("受极端天气影响，南方多地电力负荷创历史新高，电网企业启动需求响应，引导工商业错峰用电，并加快风电光伏并网，目前供需总体平衡。",
         "南方电力负荷创新高，电网启动需求响应并加快风光并网，供需总体平衡。"),
        ("某电商平台公布年度消费报告，显示银发族线上购物增速最快，健康养生与家政服务类订单翻倍，平台据此优化适老化界面与配送方案。",
         "银发族线上购物增速最快，健康与家政订单翻倍，平台优化适老化界面与配送。"),
        ("考古队在遗址发现一处保存完好的汉代粮仓，出土炭化粟米与农具，为研究古代仓储与农业经济提供实物证据。",
         "汉代粮仓遗址出土炭化粟米与农具，为古代仓储与农业经济研究提供实物证据。"),
    ]
    backgrounds = [
        "【导读】以下为新闻正文。", "【快讯】记者从权威渠道获悉，",
        "【深度】综合多方信息，", "据最新通报，", "在今日举行的发布会上，",
    ]
    for art, summary in articles:
        for bg in backgrounds:
            rows.append({"article": f"{bg}{art}", "answer": summary})
    while len(rows) < 300:
        for art, summary in articles:
            rows.append({"article": art, "answer": summary})
            if len(rows) >= 300:
                break
    return rows[:300]


def main() -> None:
    print("生成复杂评测数据集：")
    write_jsonl("multihop_qa.jsonl", build_multihop_qa())
    write_jsonl("codegen.jsonl", build_codegen())
    write_jsonl("classification.jsonl", build_classification())
    write_jsonl("summarization.jsonl", build_summarization())
    print("完成。")


if __name__ == "__main__":
    main()
