import json
import os
from dataclasses import dataclass, field
from pathlib import Path


class SettingsFileError(ValueError):
    pass


# (user id, server id) -> (flat, percent). Server id is None for DMs.
SphereBonus = dict[tuple[int, int | None], tuple[int, int]]


@dataclass
class PlayerSettings:
    auto_users: set[int] = field(default_factory=set)
    colorblind_users: set[int] = field(default_factory=set)
    sphere_bonus: SphereBonus = field(default_factory=dict)


def _server(value) -> int | None:
    return None if value is None else int(value)


def load_settings(path: Path | None) -> PlayerSettings:
    if path is None or not path.exists():
        return PlayerSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PlayerSettings(
            auto_users={int(u) for u in data.get("auto_users", [])},
            colorblind_users={int(u) for u in data.get("colorblind_users", [])},
            sphere_bonus={
                (int(b["user"]), _server(b["server"])): (
                    int(b["flat"]),
                    int(b["percent"]),
                )
                for b in data.get("sphere_bonus", [])
            },
        )
    except (ValueError, TypeError, AttributeError, KeyError) as err:
        raise SettingsFileError(
            f"{path} is not a valid settings file ({err}). Fix it or delete it."
        ) from err


def write_json_atomic(path: Path, data: dict) -> None:
    # Write a temporary file, then swap it in, so a crash mid-write can't leave
    # a half-written file behind.
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def save_settings(path: Path | None, settings: PlayerSettings) -> None:
    if path is None:
        return
    data = {
        "auto_users": sorted(settings.auto_users),
        "colorblind_users": sorted(settings.colorblind_users),
        "sphere_bonus": [
            {"user": user, "server": server, "flat": flat, "percent": percent}
            for (user, server), (flat, percent) in sorted(
                settings.sphere_bonus.items(),
                key=lambda item: (item[0][0], item[0][1] or 0),
            )
        ],
    }
    write_json_atomic(path, data)
