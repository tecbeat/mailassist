"""Root conftest — prevents pytest from collecting source functions as tests."""

from app.services.calendar import test_caldav_connection

# Prevent pytest from treating this source function as a test
test_caldav_connection.__test__ = False  # type: ignore[attr-defined]
