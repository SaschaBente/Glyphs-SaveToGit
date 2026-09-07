# Save to Git — the commit sheet
#
# The user interface for "Save to Git…": a sheet attached to the font window
# with a field for the commit message, the previous commits underneath, and a
# button to push everything to GitHub.

import os
import subprocess

from AppKit import NSFont
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
                minSize=(420, 360),
                autosaveName="de.kutilek.SaveToGit.window",
            )
        else:
            self.w = vanilla.Sheet(
                (520, 460),
                parentWindow,
                minSize=(420, 360),
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
        ok, out = git(["remote"], self.fontdir)
        return ok and bool(out.strip())

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

        push_title = Glyphs.localize(
            {"en": "Push to GitHub", "de": "Zu GitHub pushen"}
        )
        if ahead:
            push_title += f" ({ahead})"
        self.w.pushButton.setTitle(push_title)

        # Work out whether pushing is possible at all, and why not.
        # ahead is None when the branch has no upstream yet, which still
        # means there is something to push.
        if not self.has_remote():
            self.push_reason = Glyphs.localize(
                {
                    "en": "This repository has no remote, so there is "
                    "nowhere to push to. Add one on GitHub first.",
                    "de": "Dieses Repository hat kein Remote, es gibt also "
                    "nichts zum Pushen. Lege zuerst eines auf GitHub an.",
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
