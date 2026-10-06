import ast
from pathlib import Path

from src.bot.rewards import (
    PAIR_WINDOW_MS,
    REWARDS_PLACEHOLDER,
    ChannelLog,
    created_ms,
    parse_rewards,
)

DUMPS = Path(__file__).resolve().parent.parent / "data" / "mudae"


def dump_field(name: str, field: str) -> str:
    for line in (DUMPS / name).read_text().splitlines():
        if line.startswith(f"{field}: "):
            return line.split(": ", 1)[1]
    raise KeyError(field)


def dump_content(name: str) -> str:
    return ast.literal_eval(dump_field(name, "content"))


def test_finished_oc_rewards_give_each_click_in_order():
    rewards = parse_rewards(dump_content("oc_rewards_finished.txt"))
    assert [r.emoji for r in rewards] == ["spB", "spT", "spT", "spG", "spB"]
    assert [r.spheres for r in rewards] == [10, 20, 20, 35, 10]


def test_the_stock_total_is_never_read_as_a_reward():
    text = dump_content("oc_rewards_finished.txt")
    assert "Stock" in text
    assert sum(r.spheres for r in parse_rewards(text)) == 95


def test_oq_rewards_read_free_purples_and_the_red():
    rewards = parse_rewards(dump_content("oq_rewards_finished.txt"))
    assert [r.emoji for r in rewards] == [
        "spY", "spT", "spG", "spP", "spP", "spP", "sp", "spG",
    ]  # fmt: skip
    assert [r.spheres for r in rewards] == [55, 20, 35, 5, 5, 5, 150, 35]


def test_oh_midgame_rewards_have_one_line_per_click_so_far():
    rewards = parse_rewards(dump_content("oh_rewards_midgame.txt"))
    assert [r.emoji for r in rewards] == ["spB", "spB", "spB", "spP"]


def test_the_placeholder_has_no_rewards():
    text = dump_content("rewards_placeholder.txt")
    assert text == REWARDS_PLACEHOLDER
    assert parse_rewards(text) == []


def test_large_amounts_with_commas_are_read_whole():
    (reward,) = parse_rewards("<:sp:1437140700604137554> **+1,050**")
    assert reward.spheres == 1050


def test_message_ids_give_the_gaps_seen_in_the_dumps():
    oq_board = int(dump_field("oq_red_midgame.txt", "message id"))
    oq_rewards = int(dump_field("oq_rewards_finished.txt", "message id"))
    assert created_ms(oq_rewards) - created_ms(oq_board) == 675


def at(ms: int) -> int:
    """A message ID created ms milliseconds after an arbitrary start."""
    return (1_000_000 + ms) << 22


def test_a_lone_board_and_rewards_message_pair():
    log = ChannelLog()
    log.add_board(1, at(0))
    log.add_rewards(1, at(680))
    assert log.rewards_for(1, at(0)) == at(680)


def test_real_ids_from_the_dumps_pair():
    board = int(dump_field("oq_red_midgame.txt", "message id"))
    rewards = int(dump_field("oq_rewards_finished.txt", "message id"))
    log = ChannelLog()
    log.add_board(1, board)
    log.add_rewards(1, rewards)
    assert log.rewards_for(1, board) == rewards


def test_two_rewards_messages_in_the_window_pair_with_nothing():
    log = ChannelLog()
    log.add_board(1, at(0))
    log.add_rewards(1, at(400))
    log.add_rewards(1, at(900))
    assert log.rewards_for(1, at(0)) is None


def test_another_board_just_before_the_rewards_message_blocks_pairing():
    log = ChannelLog()
    log.add_board(1, at(0))
    log.add_board(1, at(300))
    log.add_rewards(1, at(700))
    assert log.rewards_for(1, at(0)) is None
    assert log.rewards_for(1, at(300)) is None


def test_rewards_outside_the_window_or_before_the_board_do_not_pair():
    log = ChannelLog()
    log.add_rewards(1, at(-100))
    log.add_board(1, at(0))
    log.add_rewards(1, at(PAIR_WINDOW_MS + 1))
    assert log.rewards_for(1, at(0)) is None


def test_other_channels_do_not_count():
    log = ChannelLog()
    log.add_board(1, at(0))
    log.add_board(2, at(100))
    log.add_rewards(1, at(500))
    log.add_rewards(2, at(600))
    assert log.rewards_for(1, at(0)) == at(500)
    assert log.rewards_for(2, at(100)) == at(600)


def test_forgetting_drops_old_messages_only():
    log = ChannelLog()
    log.add_board(1, at(0))
    log.add_rewards(1, at(500))
    log.add_board(1, at(10_000))
    log.forget_before(created_ms(at(5_000)))
    assert log.boards == {1: [at(10_000)]}
    assert log.rewards == {}


def test_an_earlier_games_rewards_message_does_not_get_in_the_way():
    log = ChannelLog()
    log.add_rewards(1, at(-100))
    log.add_board(1, at(0))
    log.add_rewards(1, at(500))
    assert log.rewards_for(1, at(0)) == at(500)
