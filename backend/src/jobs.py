import logging
from sqlalchemy import text
from src.database import SessionLocal

logger = logging.getLogger(__name__)

def sync_sessions_nightly():
    logger.info("Starting nightly sync of sessions from raw_events...")
    db = SessionLocal()
    try:
        query = text("""
            INSERT INTO sessions (
                session_id, 
                start_time, 
                end_time, 
                duration_seconds, 
                is_long_session, 
                avg_position_seconds, 
                video_count
            )
            SELECT 
                session_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) as duration_seconds,
                (EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) > 1800) as is_long_session,
                AVG(position_seconds) as avg_position_seconds,
                COUNT(DISTINCT video_id) as video_count
            FROM raw_events
            GROUP BY session_id
            ON CONFLICT (session_id) DO UPDATE SET
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                duration_seconds = EXCLUDED.duration_seconds,
                is_long_session = EXCLUDED.is_long_session,
                avg_position_seconds = EXCLUDED.avg_position_seconds,
                video_count = EXCLUDED.video_count;
        """)
        
        # Execute query
        db.execute(query)
        db.commit()
        logger.info("Successfully completed nightly sync of sessions.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error during nightly sessions sync: {e}")
    finally:
        db.close()
