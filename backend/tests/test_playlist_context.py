import pytest

from src.services.playlist_context import build_commute_rows


class FakeResult:
    def mappings(self):
        return self

    def all(self):
        return []


class FakeDb:
    def __init__(self):
        self.query = None
        self.params = None

    def execute(self, query, params):
        self.query = str(query)
        self.params = params
        return FakeResult()


def test_commute_rows_uses_configurable_weights_and_normalized_scoring():
    db = FakeDb()

    assert build_commute_rows(db, limit=12, play_weight=0.7, implicit_weight=0.3) == []
    assert db.params == {"limit": 12, "play_weight": 0.7, "implicit_weight": 0.3}
    assert "normalized_intentional_plays" in db.query
    assert "LN(1 + intentional_plays)" in db.query


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"play_weight": -0.1},
        {"implicit_weight": -0.1},
        {"play_weight": 0, "implicit_weight": 0},
    ],
)
def test_commute_rows_rejects_invalid_ranking_parameters(kwargs):
    with pytest.raises(ValueError):
        build_commute_rows(FakeDb(), **kwargs)
