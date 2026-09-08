# Save to Git

A plugin for Glyphs.app that saves your font and commits the changes to a git repository. Well suited if you just want to keep track of your changes.

If you collaborate with others on a font through Git, you will definitely need another tool, as the need to compare and merge different revisions will probably arise. _Save to Git_ doesn't handle this. Maybe try [MergeGlyphs](https://glyphsapp.com/tools/mergeglyphs) and [CommitGlyphs](https://github.com/jenskutilek/SmartTypography-Extension/tree/safari/assets).

## Usage

Instead of using the normal Save command, use `File > Save to Git`. This will save your file and commit the changes to the git repository the current file is part of.

Committing and pushing are two separate commands, so that saving your work does not drag the rest of git along with it.

### Committing with your own message

`File > Commit to Git…` saves the file like the plain command, then opens a small sheet with one thing on it: a **commit message** field, prefilled with the message that `Save to Git` would have written by itself. Edit it, or type your own, and press **Commit**. The sheet closes and Glyphs shows a notification with the message. Return commits, Escape cancels.

Nothing else happens: no pushing, no lists, no other buttons. If there is nothing to commit, or git refuses, the sheet stays open and says so.

The sheet appears straight away, with `Update <Family> <Master>` already in the field. Saving the font and working out *which glyphs* changed is the slow part — on a large family it means writing several megabytes and comparing every glyph against the previous version — so it happens once the sheet is on screen, and the message is filled in with the glyph names when it is done. If you have started typing by then, what you typed is kept.

### Pushing

`File > Push to GitHub…` opens a separate sheet showing the last 5 commits, the way GitHub Desktop does — message, short commit ID, who made it and when. A bullet (●) marks the ones that have not been pushed yet, and the header line says which branch goes where.

One **Push to GitHub** button sends them, showing how many are waiting (`Push to GitHub (3)`). If the branch has no upstream yet, it is set to `origin` on the first push. When the button is not available the sheet says why, in its status line and as a tooltip: either everything has been pushed already, or there is nowhere to push to.

This command neither saves nor commits — it only pushes what you have already committed.

### Putting the repository on GitHub

A repository that was made locally (`git init`, or *Create New Repository* in GitHub Desktop) is not connected to GitHub, so there is nothing to push to. The push sheet then offers **Publish to GitHub…** in place of the push button, which creates the repository on GitHub and pushes everything committed so far to it. From then on the push button sends your commits to that same repository, like any normal clone.

It asks before creating anything, and lets you edit the name and the owner: `SaschaBente/my-font` makes it yours, `dinamo-typefaces/my-font` puts it in that organisation. You choose private or public in the same dialog.

This uses the [GitHub CLI](https://cli.github.com), which needs to be installed (`brew install gh`) and signed in once (`gh auth login`). The sheet says so if it is not.

### Pushing to a folder

If you would rather not use GitHub at all, **Choose Folder…** sits next to it. Pick a folder — on a server, an external disk, a shared drive — and it becomes the place this font is pushed to:

- The folder has to be **outside the repository** the font is in. A copy kept inside the thing it copies is no copy at all, so the picker opens next to your repository rather than in it.
- An **empty folder** becomes the repository itself.
- A folder that is **not empty** gets a repository created inside it, named after your own (`Meteora.git`).
- An existing repository that was made this way is simply reused.
- A **working copy** (a normal checkout with a `.git` folder) is refused, because git will not push into one.

Since a folder is not GitHub, the push button is then labelled just **Push**. The button disappears once a remote is set up.

If that folder later goes missing — deleted, on a disk that is not plugged in, on a server that is not mounted — the sheet says so and offers **Choose Folder…** again, and picking a new one repoints the existing remote instead of adding a second.

## Known Issues

- The `git` command line utility must be installed on your system (see below for instructions).
- The git repository must already be set up, and the Glyphs file must have been saved and committed.
- Set your own shortcut via system preferences.
- The sheet needs the `vanilla` module, which you can install from `Window > Plugin Manager > Modules`. Without it, `File > Save to Git` still works.
- Pushing uses the credentials git is already set up with; it never asks for a password. If pushing fails because there are no stored credentials, set them up once in the Terminal (for example with `gh auth login` or by pushing that repository manually).

## Git Installation

If you don't have the `git` command line utility installed, you can do so by opening the Terminal app and entering this command:

```bash
xcode-select --install
```
