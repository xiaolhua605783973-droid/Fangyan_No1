from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Optional

from db.models import Base, RecognitionRecord
from core.logger import get_logger

logger = get_logger(__name__)


class RecordRepository:
    """语音识别记录数据访问层（异步写入，不阻塞API响应）"""

    def __init__(self, database_url: str):
        self._engine = create_engine(database_url, pool_pre_ping=True)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    def save(self, record: RecognitionRecord) -> None:
        """同步写入记录（在后台任务中调用，不阻塞响应）"""
        session: Session = self._Session()
        try:
            session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("db_save_failed", error=str(e))
        finally:
            session.close()

    def get_by_audio_hash(self, audio_hash: str) -> Optional[RecognitionRecord]:
        """根据音频哈希查询历史记录"""
        session: Session = self._Session()
        try:
            return session.query(RecognitionRecord).filter_by(
                audio_hash=audio_hash
            ).order_by(RecognitionRecord.created_at.desc()).first()
        finally:
            session.close()
