# Save to Git — the commit sheet
#
# The user interface for "Save to Git…": a sheet attached to the font window
# with a field for the commit message, the previous commits underneath, and a
# button to push everything to GitHub.

import os
import subprocess

from AppKit import NSFont, NSModalResponseOK, NSOpenPanel, NSURL
from GlyphsApp import Glyphs

import vanilla


# git can block forever if it decides to ask for credentials, so it is always
# run with the prompt disabled and a timeout.
GIT_TIMEOUT = 20
PUSH_TIMEOUT = 120

# Commits that have not been pushed yet are marked in the list.
UNPUSHED_MARKER = "●  "
PUSHED_MARKER = "     "

LOG_LIMIT = 50


def git(args, cwd, timeout=GIT_TIMEOUT):
    """Run a git command and return (success, output).

    Never raises, never prompts, never blocks indefinitely. The output is
    stdout and stderr combined, as stripped text.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            env=env,
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"git {args[0]} timed out after {timeout} seconds."
    except OSError as e:
        return False, f"Could not run git: {e}"
    output = result.stdout.decode("utf-8", "replace").strip()
    return result.returncode == 0, output


def is_git_repo(path):
    ok, _ = git(["rev-parse", "--show-toplevel"], path)
    return ok


def repo_kind(path):
    """What kind of repository a folder itself is: "bare", "checkout", None.

    This looks at the folder only. Asking git would walk up to a parent
    repository, which would misjudge an empty folder inside one.
    """
    if os.path.isdir(os.path.join(path, ".git")):
        return "checkout"
    if os.path.isfile(os.path.join(path, "HEAD")) and os.path.isdir(
        os.path.join(path, "objects")
    ):
        return "bare"
    return None


def is_empty_dir(path):
    """Whether a folder holds nothing worth worrying about."""
    ignore = {".DS_Store", ".localized"}
    try:
        return not [e for e in os.listdir(path) if e not in ignore]
    except OSError:
        return False


class CommitSheet:
    """The "Save to Git…" sheet for one font."""

    def __init__(self, plugin, font, fontdir, fontfile, suggested_msg):
        self.plugin = plugin
        self.font = font
        self.fontdir = fontdir
        self.fontfile = fontfile
        # Why the push button is disabled, if it is. Set by reload().
        self.push_reason = ""

        title = Glyphs.localize({"en": "Save to Git", "de": "In Git sichern"})
        parentWindow = plugin.parent_window(font)
        if parentWindow is None:
            # No document window to attach to: use a normal window instead.
            self.w = vanilla.Window(
                (520, 460),
                title,
                # Narrower than this and the buttons at the bottom collide.
                minSize=(520, 360),
                autosaveName="de.kutilek.SaveToGit.window",
            )
        else:
            self.w = vanilla.Sheet(
                (520, 460),
                parentWindow,
                # Narrower than this and the buttons at the bottom collide.
                minSize=(520, 360),
                maxSize=(900, 1000),
                autosaveName="de.kutilek.SaveToGit.sheet",
            )

        self.w.title = vanilla.TextBox(
            (16, 14, -16, 18), font.familyName or fontfile
        )
        self.w.title.getNSTextField().setFont_(NSFont.boldSystemFontOfSize_(13))
        self.w.subtitle = vanilla.TextBox(
            (16, 34, -16, 14), self.branch_line(), sizeStyle="small"
        )

        self.w.messageLabel = vanilla.TextBox(
            (16, 62, -16, 14),
            Glyphs.localize(
                {"en": "Commit message", "de": "Commit-Beschreibung"}
            ),
            sizeStyle="small",
        )
        self.w.message = vanilla.EditText(
            (16, 82, -130, 22),
            suggested_msg,
            placeholder=suggested_msg,
            callback=self.messageChangedCallback,
        )
        self.w.commitButton = vanilla.Button(
            (-118, 81, 102, 24),
            Glyphs.localize({"en": "Commit", "de": "Committen"}),
            callback=self.commitCallback,
        )

        self.w.line = vanilla.HorizontalLine((16, 120, -16, 1))
        self.w.logLabel = vanilla.TextBox(
            (16, 132, -16, 14),
            Glyphs.localize(
                {"en": "Previous commits", "de": "Bisherige Commits"}
            ),
            sizeStyle="small",
        )
        self.w.log = vanilla.List(
            (16, 152, -16, -86),
            [],
            showColumnTitles=False,
            allowsMultipleSelection=False,
            allowsEmptySelection=True,
            allowsSorting=False,
            drawFocusRing=False,
            rowHeight=17,
        )

        self.w.status = vanilla.TextBox(
            (16, -78, -16, 32), "", sizeStyle="small"
        )

        self.w.doneButton = vanilla.Button(
            (16, -40, 90, 24),
            Glyphs.localize({"en": "Done", "de": "Fertig"}),
            callback=self.closeCallback,
        )
        self.w.pushButton = vanilla.Button(
            (-176, -40, 160, 24),
            Glyphs.localize({"en": "Push to GitHub", "de": "Zu GitHub pushen"}),
            callback=self.pushCallback,
        )
        # Only shown when there is no remote to push to yet.
        self.w.chooseFolderButton = vanilla.Button(
            (-326, -40, 144, 24),
            Glyphs.localize({"en": "Choose Folder…", "de": "Ordner wählen…"}),
            callback=self.chooseFolderCallback,
        )

        self.w.setDefaultButton(self.w.commitButton)
        self.w.doneButton.bind("\x1b", [])

        ahead = self.reload()
        self.messageChangedCallback(self.w.message)
        # Say why pushing is not possible, instead of only disabling the
        # button, which looks like a bug.
        if self.push_reason:
            self.set_status(self.push_reason)
        elif ahead:
            self.set_status(self.waiting_text(ahead))

    # Information about the repository

    @property
    def branch(self):
        ok, branch = git(["rev-parse", "--abbrev-ref", "HEAD"], self.fontdir)
        return branch.strip() if ok else ""

    def branch_line(self):
        ok, root = git(["rev-parse", "--show-toplevel"], self.fontdir)
        root = os.path.basename(root) if ok else str(self.fontdir)
        branch = self.branch or "?"
        return f"{self.fontfile} — {root}, {branch}"

    def has_remote(self):
        return bool(self.remote_name())

    def remote_name(self):
        """The name of the first remote, or "" if there is none."""
        ok, out = git(["remote"], self.fontdir)
        if not ok or not out.strip():
            return ""
        return out.split()[0]

    def remote_url(self):
        """The URL of the first remote, or "" if there is none."""
        name = self.remote_name()
        if not name:
            return ""
        ok, url = git(["remote", "get-url", name], self.fontdir)
        return url.strip() if ok else ""

    def missing_remote_folder(self):
        """A folder remote that is not there any more, or "".

        Folders get deleted, disks get unplugged and servers get unmounted,
        and git only says so once the push has already failed.
        """
        url = self.remote_url()
        path = url[len("file://"):] if url.startswith("file://") else url
        if path and os.path.isabs(path) and not os.path.isdir(path):
            return path
        return ""

    def repo_root(self):
        """The top level of the repository the font is in, or ""."""
        ok, root = git(["rev-parse", "--show-toplevel"], self.fontdir)
        return root.strip() if ok else ""

    def is_inside_repo(self, path):
        """Whether a folder is the repository itself or sits within it."""
        root = self.repo_root()
        if not root:
            return False
        root = os.path.realpath(root)
        path = os.path.realpath(path)
        return path == root or path.startswith(root + os.sep)

    def repo_name(self):
        """The name of the repository the font is in."""
        root = self.repo_root()
        if root:
            return os.path.basename(root)
        return os.path.splitext(self.fontfile)[0]

    def ahead_count(self):
        """How many local commits are not on the tracked remote branch.

        Returns None if the branch has no upstream yet, in which case
        everything is unpushed.
        """
        ok, out = git(["rev-list", "--count", "@{u}..HEAD"], self.fontdir)
        if not ok:
            return None
        try:
            return int(out.strip())
        except ValueError:
            return None

    @staticmethod
    def waiting_text(count):
        return Glyphs.localize(
            {
                "en": f"{count} commit(s) waiting to be pushed.",
                "de": f"{count} Commit(s) noch nicht gepusht.",
            }
        )

    # Updating the interface

    def set_status(self, text):
        self.w.status.set(text)

    def reload(self):
        """Refresh the commit list and the state of the push button."""
        ahead = self.ahead_count()
        ok, out = git(
            ["log", f"-{LOG_LIMIT}", "--pretty=format:%s"], self.fontdir
        )
        subjects = out.splitlines() if ok and out else []

        items = []
        for i, subject in enumerate(subjects):
            # Without an upstream, none of the commits have been pushed.
            unpushed = i < ahead if ahead is not None else True
            items.append(
                (UNPUSHED_MARKER if unpushed else PUSHED_MARKER) + subject
            )
        self.w.log.set(items)

        # Pushing to a folder is not pushing to GitHub, so say what it is.
        url = self.remote_url()
        if url and "github.com" not in url:
            push_title = Glyphs.localize({"en": "Push", "de": "Pushen"})
        else:
            push_title = Glyphs.localize(
                {"en": "Push to GitHub", "de": "Zu GitHub pushen"}
            )
        if ahead:
            push_title += f" ({ahead})"
        self.w.pushButton.setTitle(push_title)

        # Work out whether pushing is possible at all, and why not.
        # ahead is None when the branch has no upstream yet, which still
        # means there is something to push.
        missing = self.missing_remote_folder()
        if not url:
            self.push_reason = Glyphs.localize(
                {
                    "en": "This repository has nowhere to push to yet. "
                    "Choose a folder to push to.",
                    "de": "Dieses Repository hat noch kein Ziel zum Pushen. "
                    "Wähle einen Ordner zum Pushen.",
                }
            )
        elif missing:
            self.push_reason = Glyphs.localize(
                {
                    "en": f"The folder “{missing}” is not there any more. "
                    "Choose another folder to push to.",
                    "de": f"Den Ordner „{missing}“ gibt es nicht mehr. "
                    "Wähle einen anderen Ordner zum Pushen.",
                }
            )
        elif ahead == 0:
            self.push_reason = Glyphs.localize(
                {
                    "en": "Everything is pushed.",
                    "de": "Alles ist gepusht.",
                }
            )
        else:
            self.push_reason = ""

        self.w.pushButton.enable(not self.push_reason)
        self.w.pushButton.getNSButton().setToolTip_(self.push_reason)
        # The picker is of use while there is nowhere to push, and again
        # once the folder that was chosen has gone missing.
        self.w.chooseFolderButton.show(not url or bool(missing))
        return ahead

    # Callbacks

    def messageChangedCallback(self, sender):
        self.w.commitButton.enable(bool(sender.get().strip()))

    def commitCallback(self, sender):
        msg = self.w.message.get().strip()
        if not msg:
            return

        ok, out = git(["add", "--", self.fontfile], self.fontdir)
        if not ok:
            self.set_status(f"Could not stage {self.fontfile}: {out}")
            return

        ok, out = git(["commit", "-m", msg], self.fontdir)
        if not ok:
            if "nothing to commit" in out or "nichts zu committen" in out:
                self.set_status(
                    Glyphs.localize(
                        {
                            "en": "Nothing to commit — the file has not "
                            "changed since the last commit.",
                            "de": "Nichts zu committen — die Datei hat sich "
                            "seit dem letzten Commit nicht geändert.",
                        }
                    )
                )
            else:
                self.set_status(f"Commit failed: {out}")
            self.reload()
            return

        self.w.message.set("")
        self.messageChangedCallback(self.w.message)
        ahead = self.reload()
        committed = Glyphs.localize({"en": "Committed", "de": "Committet"})
        status = f"{committed}: “{msg}”"
        if self.push_reason:
            # Committed, but the push button is going to stay disabled.
            status += " — " + self.push_reason
        elif ahead:
            status += " — " + self.waiting_text(ahead)
        self.set_status(status)

    def chooseFolderCallback(self, sender):
        """Pick a folder to push to, and make it this repository's origin."""
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setCanCreateDirectories_(True)
        panel.setPrompt_(Glyphs.localize({"en": "Choose", "de": "Wählen"}))
        panel.setMessage_(
            Glyphs.localize(
                {
                    "en": "Choose a folder to push this font to. An empty "
                    "folder becomes the repository itself; in a folder that "
                    "is not empty, one is created inside it.",
                    "de": "Wähle einen Ordner, in den diese Schrift gepusht "
                    "werden soll. Ein leerer Ordner wird selbst zum "
                    "Repository; in einem nicht leeren wird eines angelegt.",
                }
            )
        )
        # Start next to the repository rather than inside it, since a folder
        # within it cannot be used anyway.
        root = self.repo_root()
        if root:
            panel.setDirectoryURL_(
                NSURL.fileURLWithPath_(os.path.dirname(root))
            )

        if panel.runModal() != NSModalResponseOK:
            return

        chosen = str(panel.URLs()[0].path())
        target = self.prepare_remote_folder(chosen)
        if target is None:
            return

        # Repoint the remote if there already is one, which is the case when
        # the folder chosen earlier has gone missing.
        name = self.remote_name()
        if name:
            ok, out = git(["remote", "set-url", name, target], self.fontdir)
        else:
            ok, out = git(["remote", "add", "origin", target], self.fontdir)
        if not ok:
            self.set_status(f"Could not set the remote: {out}")
            return

        # Drop what we remember of the previous folder, so the commits are
        # not counted as pushed when the new folder is empty.
        git(["fetch", "--prune", self.remote_name() or "origin"], self.fontdir)

        self.reload()
        self.messageChangedCallback(self.w.message)
        self.set_status(
            Glyphs.localize(
                {
                    "en": f"This font now pushes to {target}",
                    "de": f"Diese Schrift pusht jetzt nach {target}",
                }
            )
        )

    def prepare_remote_folder(self, chosen):
        """Return a folder that can be pushed to, creating it if needed.

        Returns None and explains itself in the status line if the chosen
        folder cannot be used.
        """
        # A copy kept inside the repository it copies is no copy at all, and
        # it would sit in the working tree as untracked clutter.
        if self.is_inside_repo(chosen):
            self.set_status(
                Glyphs.localize(
                    {
                        "en": "That folder is inside this repository itself. "
                        "Choose one outside it, so the copy is somewhere "
                        "else.",
                        "de": "Dieser Ordner liegt im Repository selbst. "
                        "Wähle einen außerhalb, damit die Kopie woanders "
                        "liegt.",
                    }
                )
            )
            return None

        kind = repo_kind(chosen)
        if kind == "bare":
            # Already a repository meant to be pushed to.
            return chosen

        if kind == "checkout":
            self.set_status(
                Glyphs.localize(
                    {
                        "en": "That folder is a working copy, and git "
                        "refuses to push into one. Choose an empty folder "
                        "instead.",
                        "de": "Dieser Ordner ist eine Arbeitskopie, und git "
                        "weigert sich, dorthin zu pushen. Wähle "
                        "stattdessen einen leeren Ordner.",
                    }
                )
            )
            return None

        # Not a repository yet: make one. An empty folder becomes the
        # repository, otherwise it gets one inside it, named after this repo.
        if is_empty_dir(chosen):
            target = chosen
        else:
            target = os.path.join(chosen, self.repo_name() + ".git")
            if os.path.exists(target) and repo_kind(target) != "bare":
                self.set_status(
                    f"There is already something called "
                    f"{os.path.basename(target)} in that folder."
                )
                return None

        ok, out = git(["init", "--bare", target], chosen)
        if not ok:
            self.set_status(f"Could not create a repository there: {out}")
            return None
        return target

    def pushCallback(self, sender):
        self.w.pushButton.enable(False)
        self.w.commitButton.enable(False)
        self.set_status(Glyphs.localize({"en": "Pushing…", "de": "Pushe…"}))
        # Let the sheet redraw before git blocks the main thread.
        self.plugin.schedule_push(self)

    def performPush(self):
        ok, out = git(["push"], self.fontdir, timeout=PUSH_TIMEOUT)
        if not ok and "no upstream branch" in out:
            # First push of this branch: set the upstream along the way.
            branch = self.branch
            if branch:
                ok, out = git(
                    ["push", "--set-upstream", "origin", branch],
                    self.fontdir,
                    timeout=PUSH_TIMEOUT,
                )

        if ok:
            url = self.remote_url()
            if url and "github.com" not in url:
                # Pushing to a folder: say which one.
                self.set_status(
                    Glyphs.localize(
                        {"en": f"Pushed to {url}", "de": f"Nach {url} gepusht"}
                    )
                )
            else:
                self.set_status(
                    Glyphs.localize(
                        {"en": "Pushed to GitHub.", "de": "Zu GitHub gepusht."}
                    )
                )
        else:
            self.set_status(f"Push failed: {out}")
        self.reload()
        self.messageChangedCallback(self.w.message)

    def closeCallback(self, sender):
        self.w.close()

    def open(self):
        self.w.open()
        self.w.message.selectAll()
