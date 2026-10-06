import discord
from discord import app_commands
from discord.enums import AppCommandType

from src.bot.inspector import describe_message, register_inspector


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _button(name, emoji_id, style, disabled=False):
    return _Obj(
        type=discord.ComponentType.button,
        style=style,
        emoji=discord.PartialEmoji(name=name, id=emoji_id),
        label=None,
        disabled=disabled,
        custom_id=f"cid-{name}",
    )


def _message():
    rows = [
        _Obj(
            children=[
                _button("spR", 111, discord.ButtonStyle.primary, disabled=True),
                _button("hidden", 222, discord.ButtonStyle.secondary),
            ]
        ),
        _Obj(children=[_button("spB", 333, discord.ButtonStyle.secondary)]),
    ]
    author = _Obj(id=123456789, bot=True, __str__=lambda self: "Mudae")
    return _Obj(
        author=author,
        id=42,
        content="You can click 5 times on the buttons below",
        embeds=[],
        components=rows,
    )


def test_describe_lists_every_button_with_emoji_style_and_position():
    dump = describe_message(_message())
    assert "components found: 3" in dump
    assert "0.0 | type=ComponentType.button | style=primary | emoji=spR:111" in dump
    assert "disabled=True" in dump
    assert "0.1 |" in dump and "emoji=hidden:222" in dump
    assert "1.0 |" in dump and "emoji=spB:333" in dump
    assert "id 123456789, bot=True" in dump


def test_inspector_registers_as_a_message_command():
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register_inspector(tree)
    command = tree.get_command("Inspect sphere board", type=AppCommandType.message)
    assert command is not None


def test_describe_keeps_the_whole_text_and_shows_replies_and_mentions():
    message = _message()
    message.content = "<:spB:1437140639987929108> **+10**\n" * 40
    message.reference = _Obj(message_id=777)
    message.mentions = [_Obj(id=55), _Obj(id=66)]
    message.interaction_metadata = _Obj(user=_Obj(id=55))
    dump = describe_message(message)
    assert dump.count("spB:1437140639987929108") == 40
    assert "replies to: 777" in dump
    assert "mentions: [55, 66]" in dump
    assert "from a command by: 55" in dump
    assert "components found: 3" in dump
