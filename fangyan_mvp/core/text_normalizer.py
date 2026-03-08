import json
import re
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


class ShaoxingDialectNormalizer:
    # 必须保留的关键医疗词汇（不做任何替换）
    PROTECTED_TERMS = frozenset([
        '头晕', '胸闷', '胸痛', '呼吸困难', '心跳',
        '摔倒', '出血', '骨折', '昏迷', '抽搐',
        '腹痛', '肚皮痛', '腰痛', '发烧', '血压',
    ])

    # 语气词（吴语常见语气助词：哉/伐/嗲 为绍兴话特有）
    FILLER_PATTERN = re.compile(r'[哦嘛呢啊吧哉伐嗲嗳]')

    # 口语程度词统一化（吴语"蛮""交关"在dialect_dict中处理）
    DEGREE_PATTERN = re.compile(r'非常的很|特别难受')

    def __init__(self, dict_path: str = 'config/dialect_dict.json'):
        self._dialect_map: dict[str, str] = {}
        dict_file = Path(dict_path)
        if dict_file.exists():
            with open(dict_file, encoding='utf-8') as f:
                self._dialect_map = json.load(f)
            logger.info('dialect_dict_loaded', terms=len(self._dialect_map))
        else:
            logger.warning('dialect_dict_not_found', path=dict_path)

    def normalize(self, text: str) -> str:
        if not text:
            return text
        for dialect_word, standard_word in self._dialect_map.items():
            if not any(term in dialect_word for term in self.PROTECTED_TERMS):
                text = text.replace(dialect_word, standard_word)
        text = self.DEGREE_PATTERN.sub('非常', text)
        text = self.FILLER_PATTERN.sub('', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text