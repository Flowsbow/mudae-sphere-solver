import json

import pytest

from src.bot.commands import OcService, set_auto, toggle_colorblind
from src.bot.settings import SettingsFileError


def test_auto_mode_survives_a_restart(tmp_path):
    path = tmp_path / "settings.json"
    set_auto(OcService(path), 11, on=True)
    assert OcService(path).auto_users == {11}


def test_colorblind_mode_survives_a_restart(tmp_path):
    path = tmp_path / "settings.json"
    toggle_colorblind(OcService(path), 22)
    after = OcService(path)
    assert after.letters_for.get(22) is True
    assert after.letters_for.get(11, False) is False


def test_turning_a_setting_off_is_saved_too(tmp_path):
    path = tmp_path / "settings.json"
    service = OcService(path)
    set_auto(service, 11, on=True)
    set_auto(service, 11, on=False)
    toggle_colorblind(service, 22)
    toggle_colorblind(service, 22)

    saved = json.loads(path.read_text())
    assert saved == {"auto_users": [], "colorblind_users": [], "sphere_bonus": []}
    assert OcService(path).auto_users == set()


def test_no_file_means_nothing_is_written(tmp_path):
    service = OcService()
    set_auto(service, 11, on=True)
    assert list(tmp_path.iterdir()) == []


def test_a_broken_file_stops_startup_with_a_clear_message(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    with pytest.raises(SettingsFileError, match="Fix it or delete it"):
        OcService(path)
