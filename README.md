# Save to Git

A plugin for Glyphs.app that saves your font and commits the changes to a git repository. Well suited if you just want to keep track of your changes.

If you collaborate with others on a font through Git, you will definitely need another tool, as the need to compare and merge different revisions will probably arise. _Save to Git_ doesn't handle this. Maybe try [MergeGlyphs](https://glyphsapp.com/tools/mergeglyphs) and [CommitGlyphs](https://github.com/jenskutilek/SmartTypography-Extension/tree/safari/assets).

## Usage

Instead of using the normal Save command, use `File > Save to Git`. This will save your file and commit the changes to the git repository the current file is part of.

### Writing your own commit message

`File > Save to Git…` (with the ellipsis) does the same thing, but opens a sheet on the font window first:

- A **commit message** field, prefilled with the message that `Save to Git` would have written by itself. Edit it, or type your own.
- The **Commit** button stages the font file and commits it. Return commits, Escape closes the sheet.
- **Previous commits** lists the last 50 commit messages of the repository. A bullet (●) marks the commits that have not been pushed yet.
- **Push to GitHub** pushes those commits to the remote. It shows how many are waiting and is disabled when there is nothing to push. If the branch has no upstream yet, it is set to `origin` on the first push.

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
