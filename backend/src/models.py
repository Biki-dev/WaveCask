from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from src.database import Base

class RawEvent(Base):
    __tablename__ = "raw_events"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(String, index=True, nullable=True)
    title = Column(String, nullable=False)
    channel = Column(String, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    tab_id = Column(Integer, nullable=False)
    device_id = Column(String, index=True, nullable=False)
    position_seconds = Column(Float, nullable=False)
    video_duration_seconds = Column(Float, nullable=True)
    is_autoplay = Column(Boolean, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
