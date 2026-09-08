# Save to Git

A plugin for Glyphs.app that saves your font and commits the changes to a git repository. Well suited if you just want to keep track of your changes.

If you collaborate with others on a font through Git, you will definitely need another tool, as the need to compare and merge different revisions will probably arise. _Save to Git_ doesn't handle this. Maybe try [MergeGlyphs](https://glyphsapp.com/tools/mergeglyphs) and [CommitGlyphs](https://github.com/jenskutilek/SmartTypography-Extension/tree/safari/assets).

## Usage

Instead of using the normal Save command, use `File > Save to Git`. This will save your file and commit the changes to the git repository the current file is part of.

### Writing your own commit message

`File > Save to Git…` (with the ellipsis) does the same thing, but opens a sheet on the font window first:

- A **commit message** field, prefilled with the message that `Save to Git` would have written by itself. Edit it, or type your own.
- The **Commit** button stages the font file and commits it. Return commits, Escape closes the sheet, and **Done** closes it when you have finished.
- **Previous commits** lists the last 50 commit messages of the repository. A bullet (●) marks the commits that have not been pushed yet.
- **Push to GitHub** pushes those commits to the remote. It shows how many are waiting (`Push to GitHub (3)`) and becomes available as soon as you have committed something. If the branch has no upstream yet, it is set to `origin` on the first push.

When the push button is not available, the sheet says why, both in its status line and as a tooltip: either everything has been pushed already, or the repository has nowhere to push to.

### Putting the repository on GitHub

A repository that was made locally (`git init`, or *Create New Repository* in GitHub Desktop) is not connected to GitHub, so there is nothing to push to. The sheet then offers **Publish to GitHub…**, which creates the repository on GitHub and pushes everything committed so far to it. From then on the push button sends your commits to that same repository, like any normal clone.

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
