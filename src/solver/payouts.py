from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal


def with_bonus(base: Mapping, flat: int, percent: int) -> dict:
    """Spheres per colour for a player with Mudae's sphere bonuses.

    payout = (base + flat) x (1 + percent/100), rounded to a whole sphere with
    halves rounded up. The flat bonus is Mudae's "Additional spheres: +N (spheres
    clicked + premium)" line in $kt; the percent bonus is the player's reported
    25%. Checked against 10 observed payouts on Flow's other server (flat 6,
    25%), 2026-10-03: blue 20, teal 33, green 51, purple 14, red 195 in $oq, and
    4x those in $oh. Yellow, orange and $oc games are not checked yet. Both
    bonuses come from Mudae server and user premium (Flow, 2026-10-05).
    """
    scale = Decimal(100 + percent) / 100
    return {
        color: int((scale * (value + flat)).quantize(Decimal(1), ROUND_HALF_UP))
        for color, value in base.items()
    }
