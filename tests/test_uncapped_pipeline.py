from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pandas as pd

from pipeline.analytics import get_completed_matches
from pipeline.data_service import DataService


class CompletedMatchCollectionTests(unittest.TestCase):
    def test_collects_every_completed_match_without_cap(self):
        rows = [
            {"matchId": i, "status": "played", "dateutc": f"2026-01-{(i % 28) + 1:02d}T12:00:00Z"}
            for i in range(1, 35)
        ]
        rows.append({"matchId": 99, "status": "scheduled", "dateutc": "2026-12-01T12:00:00Z"})
        frame = pd.DataFrame(rows)
        result = get_completed_matches(frame)
        self.assertEqual(len(result), 34)
        self.assertNotIn(99, result["matchId"].tolist())

    def test_no_completed_matches_does_not_fall_back_to_fixtures(self):
        frame = pd.DataFrame([
            {"matchId": 1, "status": "scheduled", "dateutc": "2026-12-01T12:00:00Z"}
        ])
        self.assertTrue(get_completed_matches(frame).empty)


class EventCacheTests(unittest.TestCase):
    def test_recent_empty_cache_is_reused_without_api_call(self):
        with TemporaryDirectory() as tmp:
            settings = SimpleNamespace(
                enable_incremental_event_fetch=True,
                force_refresh_from_api=False,
                event_cache_dir=Path(tmp),
                event_cache_recheck_missing_hours=24,
            )
            service = DataService(settings)
            service._write_cached_match_events(42, [])
            calls = []
            service.fetch_api = lambda endpoint, params=None: calls.append(endpoint) or []
            events, covered, missing = service.fetch_events_for_match_ids([42])
            self.assertEqual(events, [])
            self.assertEqual(covered, [])
            self.assertEqual(missing, [42])
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
