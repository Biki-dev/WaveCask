"""
conftest.py
-----------
Global pytest configuration for WaveCask backend tests.

Sets a dummy DATABASE_URL so that importing src.database (which is pulled in
transitively by src.services.__init__) does not raise an error when no
real PostgreSQL instance is available.

Pure-unit tests (e.g. test_recommendation_math.py) never actually touch the
database; only integration tests that explicitly request a DB fixture do.
"""
import os

# Must be set before any src.* import triggers sqlalchemy.create_engine
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy_test")
