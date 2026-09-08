# Save to Git — keyboard shortcuts
#
# A plugin can give its own menu items key equivalents, so the shortcuts do
# not have to be set up by hand in System Settings. Nothing here touches
# menu items belonging to Glyphs itself.

from AppKit import (
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
)


COMMAND = int(NSEventModifierFlagCommand)
SHIFT = int(NSEventModifierFlagShift)
OPTION = int(NSEventModifierFlagOption)
CONTROL = int(NSEventModifierFlagControl)

# Shift-Command-S and Option-Shift-Command-S. The key equivalent is the
# lowercase letter; Shift belongs in the modifiers, not in the letter.
COMMIT_SHORTCUT = ("s", COMMAND | SHIFT)
PUSH_SHORTCUT = ("s", COMMAND | SHIFT | OPTION)

# In the order Apple writes them.
MODIFIER_SYMBOLS = (
    (CONTROL, "⌃"),
    (OPTION, "⌥"),
    (SHIFT, "⇧"),
    (COMMAND, "⌘"),
)


def describe(shortcut):
    """A shortcut as it is written in a menu, e.g. "⇧⌘S"."""
    key, mask = shortcut
    symbols = "".join(symbol for flag, symbol in MODIFIER_SYMBOLS if mask & flag)
    return symbols + key.upper()


def apply_shortcut(menu_item, shortcut):
    """Give a menu item its key equivalent."""
    key, mask = shortcut
    menu_item.setKeyEquivalent_(key)
    menu_item.setKeyEquivalentModifierMask_(mask)


def clear_shortcut(menu_item):
    """Take a key equivalent away again."""
    menu_item.setKeyEquivalent_("")
    menu_item.setKeyEquivalentModifierMask_(0)


def has_shortcut(menu_item, shortcut):
    key, mask = shortcut
    return (
        str(menu_item.keyEquivalent()) == key
        and int(menu_item.keyEquivalentModifierMask()) == mask
    )


def conflicts(menu, shortcut, ignore=()):
    """The titles of menu items already using a shortcut.

    Only the menu itself is looked at, not its submenus, which is where the
    commands a shortcut would clash with live. Items in `ignore` are ours.
    """
    if menu is None:
        return []
    ours = {id(item) for item in ignore}
    found = []
    for i in range(menu.numberOfItems()):
        item = menu.itemAtIndex_(i)
        if id(item) in ours:
            continue
        if has_shortcut(item, shortcut):
            found.append(str(item.title()))
    return found
