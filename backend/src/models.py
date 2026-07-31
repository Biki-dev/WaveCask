from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.orm import relationship
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

class SessionSummary(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    duration_seconds = Column(Float, nullable=False)
    is_long_session = Column(Boolean, nullable=False)
    avg_position_seconds = Column(Float, nullable=False)
    video_count = Column(Integer, nullable=False)


    raw_events = relationship(
        "RawEvent",
        primaryjoin="RawEvent.session_id == SessionSummary.session_id",
        foreign_keys="[RawEvent.session_id]",
        viewonly=True
    )
