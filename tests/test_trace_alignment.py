"""Guards against the runtime and trace record types drifting apart.

EnvironmentRecordEntry duplicates EnvironmentRecord deliberately: trace.schema
imports nothing from the rest of the package, which is what lets trace.reader
work as a standalone analysis tool. The cost is that adding a field to one and
not the other silently drops data from every trace.
"""

from dataclasses import fields

from marionette.environment import EnvironmentRecord
from marionette.trace.schema import EnvironmentRecordEntry


def test_environment_record_fields_match_trace_entry() -> None:
    """If this fails, a field was added to one type and not the other."""
    runtime = {f.name for f in fields(EnvironmentRecord)}
    traced = set(EnvironmentRecordEntry.model_fields)
    assert runtime == traced
