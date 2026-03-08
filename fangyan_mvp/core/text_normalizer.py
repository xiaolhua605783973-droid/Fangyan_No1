import json
import re
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


class SichuanDialectNormalizer:
    """
    四川方言文本规范化器。
    将 ASR 输出的方言文本标准化，保留关键医疗词汇，便于意图识别。
    """

    # 必须保留的关键医疗词汇（不做任何替换）
    PROTECTED_TERMS = frozenset([
        "头晕", "胸闷", "胸痛", "呼吸困难", "心跳",
        "摔倒", "出血", "骨折", "昏迷", "抽搐",
        "腹痛", "肚子痛", "腰痛", "发烧", "血压",
    ])

    # 语气词（直接删除）
    FILLER_PATTERN = re.compile(r"[哦嘛嘞哈撒呢啊吧噻]")

    # 口语程度词统一化
    DEGREE_PATTERN = re.compile(r"得很|得多|得厉害|得要命|得慌")

    def __init__(self, dict_path: str = "config/dialect_dict.json"):
        self._dialect_map: dict[str, str] = {}
        dict_file = Path(dict_path)
        if dict_file.exists():
            with open(dict_file, encoding="utf-8") as f:
                self._dialect_map = json.load(f)
            logger.info("dialect_dict_loaded", terms=len(self._dialect_map))
        else:
            logger.warning("dialect_dict_not_found", path=dict_path)

    def normalize(self, text: str) -> str:
        """
        规范化流程：
        1. 方言词汇映射
        2. 口语程度词统一
        3. 去除语气词
        4. 合并多余空格
        """
        if not text:
            return text

        # 步骤1：方言词汇替换（跳过受保护词汇）
        for dialect_word, standard_word in self._dialect_map.items():
            # 仅当替换不会破坏受保护词汇时才替换
            if not any(term in dialect_word for term in self.PROTECTED_TERMS):
                text = text.replace(dialect_word, standard_word)

        # 步骤2：程度词统一
        text = self.DEGREE_PATTERN.sub("非常", text)

        # 步骤3：去除语气词
        text = self.FILLER_PATTERN.sub("", text)

        # 步骤4：整理空格
        text = re.sub(r"\s+", " ", text).strip()

        return text
