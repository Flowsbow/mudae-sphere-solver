import re

# With Mudae's $toggleletter on, every sphere emoji gets a "2" (spB2, spP2, spL2)
# and the red one is "spR2" instead of "sp": Flow's dumps of a finished $oc board,
# a finished $oh board and its rewards, 2026-10-21 (data/mudae/*_letters.txt).
# Covered tiles ("spU2") and rainbows ("spW2") haven't been seen with it yet; they
# are assumed to follow the same pattern.
LETTER_STYLE = re.compile(r"^(sp[A-Z]?)2$")


def plain_emoji(name: str | None) -> str | None:
    """The emoji name without $toggleletter's style: "spB2" -> "spB",
    "spR2" -> "sp" (red)."""
    if name is None:
        return None
    match = LETTER_STYLE.match(name)
    if match is None:
        return name
    return "sp" if match[1] == "spR" else match[1]


def plain_text(text: str) -> str:
    """Message text with every "<:spB2:123>" written as "<:spB:123>"."""
    return re.sub(r"<:(sp[A-Z]?2):", lambda m: f"<:{plain_emoji(m[1])}:", text)
