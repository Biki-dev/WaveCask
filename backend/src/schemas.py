from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class RawEventCreate(BaseModel):
    video_id: Optional[str] = None
    title: str
    channel: str
    event_type: str
    session_id: str
    tab_id: int
    device_id: str
    position_seconds: float
    video_duration_seconds: Optional[float] = None
    is_autoplay: bool
    timestamp: datetime

class RawEventResponse(RawEventCreate):
    id: int

    class Config:
        from_attributes = True

class SessionSummaryResponse(BaseModel):
    session_id: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    is_long_session: bool
    avg_position_seconds: float
    video_count: int

    class Config:
        from_attributes = True
