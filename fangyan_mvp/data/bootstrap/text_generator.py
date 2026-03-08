"""
文本变体生成器
从 templates.json 中的基础模板生成多样化的四川方言文本变体，
用于 TTS 合成和数据集构建。
"""
import json
import random
from pathlib import Path
from typing import Iterator


# 语气词前缀扩充（模拟老年人说话习惯）
_PREFIXES = ["", "", "", "哎", "哦", "嗯", "那", ""]
# 句尾语气词（四川方言特有）
_SUFFIXES = ["", "", "", "嘛", "嘛", "哦", "嘞", "哈", "嘛哦", "嘛嘞"]
# 口语化重复词（老年人常见）
_REPEATS = {
    "快": "快快",
    "帮": "帮帮",
    "来": "来来",
    "救": "救救",
}
# 同义替换词对
_SYNONYM_MAP = {
    "护士": ["护士", "护士小姐", "护士姐", "护士妹儿"],
    "医生": ["医生", "大夫", "医生叔叔", "医生哥哥"],
    "儿子": ["儿子", "崽儿", "娃儿", "儿子娃"],
    "女儿": ["女儿", "女儿娃", "闺女"],
    "老伴": ["老伴", "老伴儿", "老头子", "老婆子"],
    "电话": ["电话", "手机", "电话电话"],
    "帮忙": ["帮忙", "帮个忙", "搭把手"],
    "快来": ["快来", "快点来", "快来嘛", "赶快来"],
}


class TextGenerator:
    """
    从模板生成四川方言文本变体。
    每条模板可生成 N 个变体，通过随机替换语气词、同义词等方式扩充。
    """

    def __init__(self, templates_path: str = "data/bootstrap/templates.json"):
        self._templates_path = Path(templates_path)
        self._templates: dict = self._load_templates()

    def _load_templates(self) -> dict:
        if not self._templates_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {self._templates_path}")
        with open(self._templates_path, encoding="utf-8") as f:
            return json.load(f)

    def generate_variations(self, text: str, n: int = 3) -> list[str]:
        """
        对单条文本生成 n 个变体。

        Args:
            text: 原始模板文本
            n: 生成数量

        Returns:
            变体列表（包含原文）
        """
        results = {text}  # 用 set 去重，第一条始终包含原文

        attempts = 0
        while len(results) < n + 1 and attempts < n * 5:
            attempts += 1
            variant = self._mutate(text)
            results.add(variant)

        return list(results)[:n + 1]

    def _mutate(self, text: str) -> str:
        """随机应用一种或多种变换"""
        mutations = [
            self._add_prefix,
            self._add_suffix,
            self._replace_synonyms,
            self._add_repeat,
            self._add_filler,
        ]
        # 随机选 1-2 种变换叠加
        selected = random.sample(mutations, k=random.randint(1, 2))
        result = text
        for fn in selected:
            result = fn(result)
        return result

    def _add_prefix(self, text: str) -> str:
        prefix = random.choice(_PREFIXES)
        return prefix + text if prefix else text

    def _add_suffix(self, text: str) -> str:
        # 如果文本末尾已有语气词则不重复加
        for suf in ["嘛", "哦", "嘞", "哈"]:
            if text.endswith(suf):
                return text
        suffix = random.choice(_SUFFIXES)
        return text + suffix if suffix else text

    def _replace_synonyms(self, text: str) -> str:
        result = text
        for word, synonyms in _SYNONYM_MAP.items():
            if word in result:
                result = result.replace(word, random.choice(synonyms), 1)
        return result

    def _add_repeat(self, text: str) -> str:
        for word, repeat in _REPEATS.items():
            if word in text and random.random() < 0.3:
                return text.replace(word, repeat, 1)
        return text

    def _add_filler(self, text: str) -> str:
        """插入口语化填充词"""
        fillers = ["一下", "一哈", "哈", "啊", "嘛"]
        # 在第一个动词/关键词后插入
        for char in ["喊", "叫", "找", "帮", "救"]:
            if char in text:
                idx = text.index(char) + 1
                filler = random.choice(fillers)
                return text[:idx] + filler + text[idx:]
        return text

    def iter_all_texts(
        self,
        target_per_intent: int = 50,
    ) -> Iterator[tuple[str, str, str]]:
        """
        生成所有意图的文本样本。

        Yields:
            (text, intent, risk_level)
        """
        for intent_name, intent_data in self._templates.items():
            templates_list: list[str] = (
                intent_data["templates"] + intent_data.get("dialect_variations", [])
            )
            risk_level: str = intent_data["risk_level"]

            seen: set[str] = set()
            count = 0

            # 第一轮：先输出所有原始模板
            for text in templates_list:
                if text not in seen:
                    seen.add(text)
                    yield text, intent_name, risk_level
                    count += 1
                    if count >= target_per_intent:
                        break

            if count >= target_per_intent:
                continue

            # 第二轮：循环生成变体，直到凑足 target_per_intent
            max_iters = target_per_intent * 20  # 最多尝试次数防止死循环
            iters = 0
            while count < target_per_intent and iters < max_iters:
                iters += 1
                base = random.choice(templates_list)
                variant = self._mutate(base)
                if variant not in seen:
                    seen.add(variant)
                    yield variant, intent_name, risk_level
                    count += 1
