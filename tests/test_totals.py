import json

import numpy as np
import pytest

from src.bot.totals import (
    OcResult,
    OcTotals,
    OqResult,
    OqTotals,
    Running,
    StatsFileError,
    StatsStore,
)
from src.solver.board import cell_index

PLAYER = 123456789012345678
OC_VALUE = {"RED": 150, "ORANGE": 90, "YELLOW": 55, "GREEN": 35, "TEAL": 20, "BLUE": 10}


def oc(clicks="RED ORANGE GREEN ORANGE YELLOW", followed=5, red="A1", gained=999):
    clicks = tuple(clicks.split())
    return OcResult(
        clicks=clicks,
        spheres_gained=gained,
        picks=5,
        picks_followed=followed,
        score=sum(OC_VALUE[c] for c in clicks),
        expected=344.7,
        red_cell=cell_index(red),
    )


# A real finished game's clicks: data/mudae/oq_red_finished.txt.
OQ_CLICKS = "YELLOW TEAL GREEN PURPLE PURPLE PURPLE RED GREEN GREEN GREEN"


def oq(clicks=OQ_CLICKS, followed=None, score=400.0, best=500.0, expected=380.0):
    clicks = tuple(clicks.split())
    return OqResult(
        clicks=clicks,
        spheres_gained=455,
        picks=len(clicks),
        picks_followed=len(clicks) if followed is None else followed,
        score=score,
        best=best,
        expected=expected,
    )


def test_running_totals_match_numpy():
    values = [344.0, 420.0, 251.5, 310.0, 388.25]
    running = Running()
    for x in values:
        running.add(x)
    assert running.mean == pytest.approx(np.mean(values))
    assert running.standard_error == pytest.approx(
        np.std(values, ddof=1) / np.sqrt(len(values))
    )


def test_one_value_has_a_mean_but_no_standard_error():
    running = Running()
    assert running.mean is None
    running.add(5.0)
    assert running.mean == 5.0
    assert running.standard_error is None


def test_a_followed_oc_game_counts_toward_accuracy():
    totals = OcTotals()
    totals.add(oc())
    assert totals.games == 1
    assert totals.spheres_gained == 999
    assert totals.clicked == {
        "BLUE": 0, "TEAL": 0, "GREEN": 1, "YELLOW": 1, "ORANGE": 2, "RED": 1,
    }  # fmt: skip
    assert (totals.picks, totals.picks_followed) == (5, 5)
    assert totals.followed_score.mean == 420
    assert totals.followed_luck.mean == pytest.approx(420 - 344.7)
    assert totals.followed_red_found == 1
    assert totals.red_cells[cell_index("A1")] == 1


def test_an_oc_game_with_a_skipped_pick_counts_everywhere_but_accuracy():
    totals = OcTotals()
    totals.add(oc(followed=4))
    assert totals.games == 1
    assert totals.picks_followed == 4
    assert totals.followed_luck.n == 0
    assert totals.followed_red_found == 0
    assert sum(totals.red_cells) == 1


def test_an_oc_game_cut_short_does_not_count_toward_accuracy():
    totals = OcTotals()
    totals.add(oc(clicks="BLUE BLUE TEAL", followed=3))
    assert totals.followed_luck.n == 0


def test_a_followed_oq_game_counts_its_share_of_the_best():
    totals = OqTotals()
    totals.add(oq())
    assert totals.games == 1
    assert totals.clicked["PURPLE"] == 3
    assert totals.clicked["RED"] == 1
    assert totals.followed_share.mean == pytest.approx(0.8)
    assert totals.followed_luck.mean == pytest.approx(20.0)


def test_an_oq_rainbow_is_counted_as_rainbow():
    totals = OqTotals()
    totals.add(oq(clicks=OQ_CLICKS.replace("RED", "RAINBOW")))
    assert totals.clicked["RAINBOW"] == 1
    assert totals.clicked["RED"] == 0
    assert totals.followed_share.n == 1


def test_an_oq_game_with_unused_paid_clicks_is_not_judged():
    totals = OqTotals()
    totals.add(oq(clicks="YELLOW TEAL GREEN PURPLE"))
    assert totals.games == 1
    assert totals.followed_share.n == 0


def test_an_oq_game_with_a_skipped_pick_is_not_judged():
    totals = OqTotals()
    totals.add(oq(followed=9))
    assert totals.followed_share.n == 0
    assert totals.followed_luck.n == 0


def test_totals_survive_a_restart(tmp_path):
    paths = tmp_path / "stats.json", tmp_path / "my_stats.json"
    store = StatsStore(*paths)
    store.record(PLAYER, oc())
    store.record(PLAYER, oc("BLUE TEAL GREEN YELLOW BLUE", followed=4, red="C2"))
    store.record(PLAYER, oq())
    after = StatsStore(*paths)
    assert after.all == store.all
    assert after.players == {PLAYER: store.all}


def test_each_player_gets_their_own_totals(tmp_path):
    store = StatsStore(tmp_path / "stats.json", tmp_path / "my_stats.json")
    store.record(1, oc())
    store.record(2, oc(followed=0))
    store.record(2, oq())
    assert (store.all.oc.games, store.all.oq.games) == (2, 1)
    assert store.players[1].oc.games == 1
    assert store.players[2].oc.games == 1
    assert store.players[2].oq.games == 1


def test_deleting_my_stats_is_saved_and_leaves_global_stats(tmp_path):
    paths = tmp_path / "stats.json", tmp_path / "my_stats.json"
    store = StatsStore(*paths)
    store.record(PLAYER, oc())
    assert store.delete_player(PLAYER) is True
    assert store.delete_player(PLAYER) is False
    after = StatsStore(*paths)
    assert after.players == {}
    assert after.all.oc.games == 1


def test_no_paths_means_nothing_is_written(tmp_path):
    StatsStore().record(PLAYER, oc())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "text",
    ["{not json", '{"version": 99}', '{"version": 1}', "[]", '{"version": 1, "oc": 5}'],
)
def test_a_broken_stats_file_stops_startup_with_a_clear_message(tmp_path, text):
    path = tmp_path / "stats.json"
    path.write_text(text)
    with pytest.raises(StatsFileError, match="Fix it or delete it"):
        StatsStore(path)


def test_a_broken_player_file_stops_startup_too(tmp_path):
    path = tmp_path / "my_stats.json"
    path.write_text('{"version": 1, "players": {"12": {"oc": {"games": 1}}}}')
    with pytest.raises(StatsFileError, match="Fix it or delete it"):
        StatsStore(None, path)


def test_global_stats_hold_no_ids_and_my_stats_only_the_player_id(tmp_path):
    paths = tmp_path / "stats.json", tmp_path / "my_stats.json"
    StatsStore(*paths).record(PLAYER, oc(gained=95))

    global_text = paths[0].read_text()
    assert str(PLAYER) not in global_text
    assert set(json.loads(global_text)) == {"version", "oc", "oq"}

    players_text = paths[1].read_text()
    assert list(json.loads(players_text)["players"]) == [str(PLAYER)]
    assert players_text.count(str(PLAYER)) == 1
