from datetime import date

import pytest

from helpers import RUN_DATE, add_parcel, add_territory, client
from territory.runner import _insert_signal, run_adapter
from territory.sources.base import Match, RawRecord, RunContext, SignalCandidate, SourceAdapter


class ExplodingAdapter(SourceAdapter):
    source_key = "exploding"

    def fetch(self, run_id):
        for i in range(3):
            yield RawRecord(self.source_key, f"r{i}", {"i": i})
        raise RuntimeError("source went away")

    def match(self, raw):
        return Match("3000000001", "apn", 0.9)

    def normalize(self, raw):
        yield SignalCandidate("t", "g", self.source_key, raw.source_record_id, 0.9, "apn",
                              "3000000001", RUN_DATE)


def test_failed_run_is_recorded_and_leaves_nothing_half_written(db, tmp_path):
    add_parcel(db, "3000000001", -117.25, 32.85)
    out = run_adapter(ExplodingAdapter, lambda conn, rid: RunContext(
        conn=conn, run_id=rid, run_date=RUN_DATE, client=client(), report_dir=tmp_path))
    assert out.status == "failed" and "source went away" in out.error
    status, msg, fin = db.execute("select status, error_message, finished_at from source_runs").fetchone()
    assert status == "failed" and "RuntimeError" in msg and fin is not None
    assert db.execute("select count(*) from raw_records").fetchone()[0] == 0
    assert db.execute("select count(*) from signals").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [("source_record_id", ""), ("source_key", ""),
                                         ("match_method", None), ("confidence", None), ("apn", None)])
def test_runner_refuses_signals_without_provenance(db, field, value):
    kw = dict(signal_type="t", signal_group="g", source_key="s", source_record_id="r",
              confidence=0.9, match_method="apn", apn="3000000001")
    kw[field] = value
    with pytest.raises(ValueError):
        _insert_signal(db, "00000000-0000-0000-0000-000000000000", SignalCandidate(**kw))
