import io

import discord
from discord import app_commands

DUMP_NAME = "board_dump.txt"


def _buttons(component, path=()):
    children = getattr(component, "children", None)
    if children is None:
        yield path, component
        return
    for i, child in enumerate(children):
        yield from _buttons(child, (*path, i))


def describe_message(message: discord.Message) -> str:
    lines = [
        f"author: {message.author} (id {message.author.id}, bot={message.author.bot})",
        f"message id: {message.id}",
        f"content: {message.content[:300]!r}",
        f"embeds: {len(message.embeds)}",
        "",
    ]
    count = 0
    for row, top in enumerate(message.components):
        for path, item in _buttons(top, (row,)):
            count += 1
            emoji = getattr(item, "emoji", None)
            emoji_text = (
                f"{emoji.name}:{emoji.id}" if emoji is not None and emoji.id else emoji
            )
            style = getattr(item, "style", None)
            lines.append(
                f"{'.'.join(map(str, path))}"
                f" | type={getattr(item, 'type', None)}"
                f" | style={getattr(style, 'name', style)}"
                f" | emoji={emoji_text}"
                f" | label={getattr(item, 'label', None)!r}"
                f" | disabled={getattr(item, 'disabled', None)}"
                f" | custom_id={getattr(item, 'custom_id', None)}"
            )
    lines.insert(4, f"components found: {count}")
    return "\n".join(lines)


def register_inspector(tree: app_commands.CommandTree) -> None:
    @tree.context_menu(name="Inspect sphere board")
    async def inspect_board(
        interaction: discord.Interaction, message: discord.Message
    ) -> None:
        dump = describe_message(message)
        file = discord.File(io.BytesIO(dump.encode()), filename=DUMP_NAME)
        await interaction.response.send_message(
            "Here's what that message's buttons contain.",
            file=file,
            ephemeral=True,
        )
