import re
from dataclasses import dataclass, field

# Everything below comes from Flow's inspector dumps, 2026-10-05:
# data/mudae/rewards_placeholder.txt, oc_rewards_finished.txt,
# oq_rewards_finished.txt and oh_rewards_midgame.txt.
REWARDS_PLACEHOLDER = "(Rewards appear here)"
# One line per click, in click order: "<:spB:1437140639987929108> **+10**".
# Purples read "(Free) **+5**"; the last line can end in "(Stock: **1,120**)",
# which has no "+" and so never matches.
REWARD_LINE = re.compile(r"<:(sp[A-Z]?):\d+>\s*(?:\(Free\)\s*)?\*\*\+([\d,]+)\*\*")
# Emoji names as in the boards (src/bot/mudae_reader.py); rainbow "spW" from
# data/mudae/oh_rainbow_finished.txt, named by Flow 2026-10-05.
EMOJI_LABEL = {
    "spB": "BLUE",
    "spT": "TEAL",
    "spG": "GREEN",
    "spY": "YELLOW",
    "spO": "ORANGE",
    "spP": "PURPLE",
    "sp": "RED",
    "spW": "RAINBOW",
}
# Discord message IDs hold their creation time in milliseconds since this epoch
# (Discord developer docs, "Snowflakes"). Flow's dumps give gaps of 0.68 s ($oq)
# and 0.39 s ($oh) between a board and its rewards message.
DISCORD_EPOCH_MS = 1420070400000
# Chosen 2026-10-05: about 3x the slowest gap seen.
PAIR_WINDOW_MS = 2000


@dataclass(frozen=True)
class Reward:
    emoji: str
    spheres: int


def parse_rewards(text: str) -> list[Reward]:
    return [
        Reward(emoji, int(amount.replace(",", "")))
        for emoji, amount in REWARD_LINE.findall(text)
    ]


def created_ms(message_id: int) -> int:
    return (message_id >> 22) + DISCORD_EPOCH_MS


@dataclass
class ChannelLog:
    """Recent sphere boards and rewards messages, per channel."""

    boards: dict[int, list[int]] = field(default_factory=dict)
    rewards: dict[int, list[int]] = field(default_factory=dict)

    def add_board(self, channel_id: int, message_id: int) -> None:
        self.boards.setdefault(channel_id, []).append(message_id)

    def add_rewards(self, channel_id: int, message_id: int) -> None:
        self.rewards.setdefault(channel_id, []).append(message_id)

    def rewards_for(self, channel_id: int, board_id: int) -> int | None:
        """The board's rewards message, or None if there isn't exactly one match.

        Pairs only when one rewards message came within PAIR_WINDOW_MS after the
        board, and no other board came within PAIR_WINDOW_MS before that message.
        """
        start = created_ms(board_id)
        after = [
            r
            for r in self.rewards.get(channel_id, [])
            if 0 <= created_ms(r) - start <= PAIR_WINDOW_MS
        ]
        if len(after) != 1:
            return None
        (rewards_id,) = after
        end = created_ms(rewards_id)
        before = [
            b
            for b in self.boards.get(channel_id, [])
            if 0 <= end - created_ms(b) <= PAIR_WINDOW_MS
        ]
        return rewards_id if before == [board_id] else None

    def forget_before(self, cutoff_ms: int) -> None:
        for log in (self.boards, self.rewards):
            for channel_id in list(log):
                kept = [m for m in log[channel_id] if created_ms(m) >= cutoff_ms]
                if kept:
                    log[channel_id] = kept
                else:
                    del log[channel_id]
