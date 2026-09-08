# Save to Git — the sheets
#
# Two separate user interfaces, one for each half of the job:
#
#   CommitSheet  "Save to Git…"      type a message, commit, the sheet closes
#   PushSheet    "Push to GitHub…"   see what would be pushed, and push it
#
# Repo is everything either of them needs to ask git, with no interface in it.

import os
import re
import shutil
import subprocess

from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSFont,
    NSMakeRect,
    NSModalResponseOK,
    NSOpenPanel,
    NSTextField,
    NSURL,
)
from GlyphsApp import Glyphs

import vanilla


# git can block forever if it decides to ask for credentials, so it is always
# run with the prompt disabled and a timeout.
GIT_TIMEOUT = 20
PUSH_TIMEOUT = 120
GH_TIMEOUT = 120

# Told apart from a real failure of the GitHub CLI.
GH_MISSING = "gh-not-installed"

# Commits that have not been pushed yet are marked in the list.
UNPUSHED_MARKER = "●"

# How many commits the push sheet shows.
LOG_LIMIT = 5

# git will not put a unit separator in a name or a subject, so it is safe
# to split the log on.
FIELD_SEP = "\x1f"


def run(argv, cwd, timeout):
    """Run a command and return (success, output).

    Never raises, never prompts, never blocks indefinitely. The output is
    stdout and stderr combined, as stripped text.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        name = os.path.basename(argv[0])
        return False, f"{name} timed out after {timeout} seconds."
    except OSError as e:
        return False, f"Could not run {os.path.basename(argv[0])}: {e}"
    output = result.stdout.decode("utf-8", "replace").strip()
    return result.returncode == 0, output


def git(args, cwd, timeout=GIT_TIMEOUT):
    """Run a git command and return (success, output)."""
    return run(["git"] + args, cwd, timeout)


def find_gh():
    """The GitHub CLI, or "".

    Glyphs is launched from the Finder, so its PATH does not include the
    places Homebrew puts things; look there directly.
    """
    for path in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh"):
        if os.access(path, os.X_OK):
            return path
    return shutil.which("gh") or ""


def gh(args, cwd, timeout=GH_TIMEOUT):
    """Run a GitHub CLI command and return (success, output)."""
    exe = find_gh()
    if not exe:
        return False, GH_MISSING
    return run([exe] + args, cwd, timeout)


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


def github_slug(name):
    """Turn a folder name into something GitHub will accept as a repo name."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return slug or "font"


def publish_argv(slug, private, root):
    """The GitHub CLI arguments that publish a repository.

    Kept apart from the interface so it can be checked without creating
    anything on GitHub.
    """
    return [
        "repo",
        "create",
        slug,
        "--private" if private else "--public",
        "--source",
        str(root),
        "--remote",
        "origin",
        "--push",
    ]


class Repo:
    """The git repository one font lives in."""

    def __init__(self, fontdir, fontfile):
        self.dir = fontdir
        self.fontfile = fontfile

    # What git knows

    def branch(self):
        ok, out = git(["rev-parse", "--abbrev-ref", "HEAD"], self.dir)
        return out.strip() if ok else ""

    def root(self):
        """The top level of the repository, or ""."""
        ok, out = git(["rev-parse", "--show-toplevel"], self.dir)
        return out.strip() if ok else ""

    def name(self):
        """The name of the repository the font is in."""
        root = self.root()
        if root:
            return os.path.basename(root)
        return os.path.splitext(self.fontfile)[0]

    def remote_name(self):
        """The name of the first remote, or "" if there is none."""
        ok, out = git(["remote"], self.dir)
        if not ok or not out.strip():
            return ""
        return out.split()[0]

    def remote_url(self):
        """The URL of the first remote, or "" if there is none."""
        name = self.remote_name()
        if not name:
            return ""
        ok, url = git(["remote", "get-url", name], self.dir)
        return url.strip() if ok else ""

    def has_remote(self):
        return bool(self.remote_name())

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

    def ahead_count(self):
        """How many commits are not on the tracked remote branch.

        Returns None if the branch has no upstream yet, in which case
        nothing has been pushed.
        """
        ok, out = git(["rev-list", "--count", "@{u}..HEAD"], self.dir)
        if not ok:
            return None
        try:
            return int(out.strip())
        except ValueError:
            return None

    def unpushed_count(self):
        """How many commits a push would send.

        Without an upstream nothing has been pushed yet, so that is every
        commit on the branch.
        """
        ahead = self.ahead_count()
        if ahead is not None:
            return ahead
        ok, out = git(["rev-list", "--count", "HEAD"], self.dir)
        if not ok:
            return 0
        try:
            return int(out.strip())
        except ValueError:
            return 0

    def recent_commits(self, limit=LOG_LIMIT):
        """The last few commits, newest first.

        Each one is a dict of id, author, when and subject.
        """
        fields = ("%h", "%an", "%ar", "%s")
        pretty = "format:" + FIELD_SEP.join(fields)
        ok, out = git(["log", f"-{limit}", f"--pretty={pretty}"], self.dir)
        if not ok or not out:
            return []
        commits = []
        for line in out.splitlines():
            parts = line.split(FIELD_SEP)
            if len(parts) != len(fields):
                continue
            commits.append(
                {
                    "id": parts[0],
                    "author": parts[1],
                    "when": parts[2],
                    "subject": parts[3],
                }
            )
        return commits

    def is_inside(self, path):
        """Whether a folder is the repository itself or sits within it."""
        root = self.root()
        if not root:
            return False
        root = os.path.realpath(root)
        path = os.path.realpath(path)
        return path == root or path.startswith(root + os.sep)

    # What git can be told to do

    def commit(self, msg):
        """Stage the font and commit it."""
        ok, out = git(["add", "--", self.fontfile], self.dir)
        if not ok:
            return False, out
        return git(["commit", "-m", msg], self.dir)

    def push(self):
        """Push, setting the upstream if the branch does not have one yet."""
        ok, out = git(["push"], self.dir, timeout=PUSH_TIMEOUT)
        if not ok and "no upstream branch" in out:
            branch = self.branch()
            if branch:
                ok, out = git(
                    ["push", "--set-upstream", "origin", branch],
                    self.dir,
                    timeout=PUSH_TIMEOUT,
                )
        return ok, out

    def set_remote(self, target):
        """Point the remote at a folder, adding it if there is none yet."""
        name = self.remote_name()
        if name:
            ok, out = git(["remote", "set-url", name, target], self.dir)
        else:
            ok, out = git(["remote", "add", "origin", target], self.dir)
        if ok:
            # Drop what we remember of the previous folder, so the commits
            # are not counted as pushed when the new folder is empty.
            git(["fetch", "--prune", self.remote_name() or "origin"], self.dir)
        return ok, out

    def account(self):
        """The signed-in GitHub account, or ""."""
        ok, out = gh(["api", "user", "--jq", ".login"], self.dir)
        return out.strip() if ok else ""

    def publish(self, slug, private):
        """Create the repository on GitHub and push to it."""
        return gh(publish_argv(slug, private, self.root() or self.dir), self.dir)

    def prepare_folder(self, chosen):
        """Return (folder to push to, error), creating a repository if needed.

        Only one of the two is ever set.
        """
        # A copy kept inside the repository it copies is no copy at all, and
        # it would sit in the working tree as untracked clutter.
        if self.is_inside(chosen):
            return None, Glyphs.localize(
                {
                    "en": "That folder is inside this repository itself. "
                    "Choose one outside it, so the copy is somewhere else.",
                    "de": "Dieser Ordner liegt im Repository selbst. Wähle "
                    "einen außerhalb, damit die Kopie woanders liegt.",
                }
            )

        kind = repo_kind(chosen)
        if kind == "bare":
            # Already a repository meant to be pushed to.
            return chosen, ""

        if kind == "checkout":
            return None, Glyphs.localize(
                {
                    "en": "That folder is a working copy, and git refuses to "
                    "push into one. Choose an empty folder instead.",
                    "de": "Dieser Ordner ist eine Arbeitskopie, und git "
                    "weigert sich, dorthin zu pushen. Wähle stattdessen "
                    "einen leeren Ordner.",
                }
            )

        # Not a repository yet: make one. An empty folder becomes the
        # repository, otherwise it gets one inside it, named after this repo.
        if is_empty_dir(chosen):
            target = chosen
        else:
            target = os.path.join(chosen, github_slug(self.name()) + ".git")
            if os.path.exists(target) and repo_kind(target) != "bare":
                return None, (
                    f"There is already something called "
                    f"{os.path.basename(target)} in that folder."
                )

        ok, out = git(["init", "--bare", target], chosen)
        if not ok:
            return None, f"Could not create a repository there: {out}"
        return target, ""


class SheetBase:
    """The window both sheets sit in."""

    def make_window(self, plugin, font, size, resizable_to=None):
        title = Glyphs.localize({"en": "Save to Git", "de": "In Git sichern"})
        parentWindow = plugin.parent_window(font)
        maxSize = resizable_to or size
        if parentWindow is None:
            # No document window to attach to: use a normal window instead.
            return vanilla.Window(
                size,
                title,
                minSize=size,
                maxSize=maxSize,
                autosaveName=f"de.kutilek.SaveToGit.{type(self).__name__}",
            )
        return vanilla.Sheet(
            size,
            parentWindow,
            minSize=size,
            maxSize=maxSize,
            autosaveName=f"de.kutilek.SaveToGit.{type(self).__name__}.sheet",
        )

    def set_status(self, text):
        self.w.status.set(text)

    def closeCallback(self, sender):
        self.w.close()

    def open(self):
        self.w.open()


class CommitSheet(SheetBase):
    """"Save to Git…": a message and a commit, nothing else.

    Committing closes the sheet, so this is the whole of it.
    """

    def __init__(self, plugin, font, repo, suggested_msg):
        self.plugin = plugin
        self.font = font
        self.repo = repo

        self.w = self.make_window(plugin, font, (460, 200), (900, 200))

        self.w.title = vanilla.TextBox(
            (16, 14, -16, 18), font.familyName or repo.fontfile
        )
        self.w.title.getNSTextField().setFont_(NSFont.boldSystemFontOfSize_(13))
        self.w.subtitle = vanilla.TextBox(
            (16, 34, -16, 14),
            f"{repo.fontfile} — {repo.name()}, {repo.branch() or '?'}",
            sizeStyle="small",
        )

        self.w.messageLabel = vanilla.TextBox(
            (16, 62, -16, 14),
            Glyphs.localize(
                {"en": "Commit message", "de": "Commit-Beschreibung"}
            ),
            sizeStyle="small",
        )
        self.w.message = vanilla.EditText(
            (16, 82, -16, 22),
            suggested_msg,
            placeholder=suggested_msg,
            callback=self.messageChangedCallback,
        )

        self.w.status = vanilla.TextBox(
            (16, 116, -16, 30), "", sizeStyle="small"
        )

        self.w.cancelButton = vanilla.Button(
            (16, -40, 90, 24),
            Glyphs.localize({"en": "Cancel", "de": "Abbrechen"}),
            callback=self.closeCallback,
        )
        self.w.commitButton = vanilla.Button(
            (-116, -40, 100, 24),
            Glyphs.localize({"en": "Commit", "de": "Committen"}),
            callback=self.commitCallback,
        )

        self.w.setDefaultButton(self.w.commitButton)
        self.w.cancelButton.bind("\x1b", [])
        self.messageChangedCallback(self.w.message)

    def messageChangedCallback(self, sender):
        self.w.commitButton.enable(bool(sender.get().strip()))

    def commitCallback(self, sender):
        msg = self.w.message.get().strip()
        if not msg:
            return

        ok, out = self.repo.commit(msg)
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
            return

        # The sheet is going away, so say what happened outside it.
        Glyphs.showNotification(self.plugin.sheet_name, msg)
        self.w.close()

    def open(self):
        self.w.open()
        self.w.message.selectAll()


class PushSheet(SheetBase):
    """"Push to GitHub…": what is about to be pushed, and the button for it."""

    def __init__(self, plugin, font, repo):
        self.plugin = plugin
        self.font = font
        self.repo = repo
        # Why the push button is disabled, if it is. Set by reload().
        self.push_reason = ""
        # What publishCallback agreed with the user, for performPublish.
        self.pending_publish = None

        self.w = self.make_window(plugin, font, (640, 400), (1200, 900))

        self.w.title = vanilla.TextBox((16, 14, -16, 18), repo.name())
        self.w.title.getNSTextField().setFont_(NSFont.boldSystemFontOfSize_(13))
        self.w.subtitle = vanilla.TextBox(
            (16, 34, -16, 14), "", sizeStyle="small"
        )

        self.w.logLabel = vanilla.TextBox(
            (16, 64, -16, 14),
            Glyphs.localize(
                {
                    "en": f"Last {LOG_LIMIT} commits",
                    "de": f"Die letzten {LOG_LIMIT} Commits",
                }
            ),
            sizeStyle="small",
        )
        self.w.log = vanilla.List(
            (16, 84, -16, -86),
            [],
            columnDescriptions=[
                {"title": "", "key": "marker", "width": 20},
                {
                    "title": Glyphs.localize(
                        {"en": "Commit", "de": "Commit"}
                    ),
                    "key": "subject",
                    "width": 260,
                    "minWidth": 120,
                    "maxWidth": 800,
                },
                {"title": "ID", "key": "id", "width": 70},
                {
                    "title": Glyphs.localize(
                        {"en": "Author", "de": "Autor"}
                    ),
                    "key": "author",
                    "width": 120,
                },
                {
                    "title": Glyphs.localize({"en": "When", "de": "Wann"}),
                    "key": "when",
                    "width": 110,
                },
            ],
            allowsMultipleSelection=False,
            allowsEmptySelection=True,
            allowsSorting=False,
            drawFocusRing=False,
            rowHeight=18,
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
        # These two take the place of the push button while there is no
        # remote: put the repository on GitHub, or push to a folder instead.
        self.w.publishButton = vanilla.Button(
            (-176, -40, 160, 24),
            Glyphs.localize(
                {"en": "Publish to GitHub…", "de": "Auf GitHub anlegen…"}
            ),
            callback=self.publishCallback,
        )
        self.w.chooseFolderButton = vanilla.Button(
            (-326, -40, 144, 24),
            Glyphs.localize({"en": "Choose Folder…", "de": "Ordner wählen…"}),
            callback=self.chooseFolderCallback,
        )

        self.w.setDefaultButton(self.w.pushButton)
        self.w.doneButton.bind("\x1b", [])

        pending = self.reload()
        if self.push_reason:
            self.set_status(self.push_reason)
        elif pending:
            self.set_status(self.waiting_text(pending))

    @staticmethod
    def waiting_text(count):
        return Glyphs.localize(
            {
                "en": f"{count} commit(s) waiting to be pushed.",
                "de": f"{count} Commit(s) noch nicht gepusht.",
            }
        )

    def reload(self):
        """Refresh the commit list and the state of the buttons."""
        pending = self.repo.unpushed_count()
        commits = self.repo.recent_commits()
        for i, commit in enumerate(commits):
            commit["marker"] = UNPUSHED_MARKER if i < pending else ""
        self.w.log.set(commits)

        url = self.repo.remote_url()
        missing = self.repo.missing_remote_folder()
        branch = self.repo.branch() or "?"
        self.w.subtitle.set(
            f"{branch} → {url}"
            if url
            else Glyphs.localize(
                {
                    "en": f"{branch} — not on GitHub yet",
                    "de": f"{branch} — noch nicht auf GitHub",
                }
            )
        )

        # Pushing to a folder is not pushing to GitHub, so say what it is.
        if url and "github.com" not in url:
            push_title = Glyphs.localize({"en": "Push", "de": "Pushen"})
        else:
            push_title = Glyphs.localize(
                {"en": "Push to GitHub", "de": "Zu GitHub pushen"}
            )
        if pending:
            push_title += f" ({pending})"
        self.w.pushButton.setTitle(push_title)

        # Work out whether pushing is possible at all, and why not.
        if not url:
            self.push_reason = Glyphs.localize(
                {
                    "en": "This repository is not on GitHub yet. Publish it "
                    "there, or choose a folder to push to instead.",
                    "de": "Dieses Repository ist noch nicht auf GitHub. Lege "
                    "es dort an, oder wähle stattdessen einen Ordner.",
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
        elif pending == 0:
            self.push_reason = Glyphs.localize(
                {"en": "Everything is pushed.", "de": "Alles ist gepusht."}
            )
        else:
            self.push_reason = ""

        self.w.pushButton.enable(not self.push_reason)
        self.w.pushButton.getNSButton().setToolTip_(self.push_reason)
        # With nowhere to push, the push button has nothing to do: offer the
        # two ways of getting a destination in its place instead.
        self.w.pushButton.show(bool(url))
        self.w.publishButton.show(not url)
        # The picker is of use while there is nowhere to push, and again
        # once the folder that was chosen has gone missing.
        self.w.chooseFolderButton.show(not url or bool(missing))
        return pending

    # Pushing

    def pushCallback(self, sender):
        self.w.pushButton.enable(False)
        self.set_status(Glyphs.localize({"en": "Pushing…", "de": "Pushe…"}))
        # Let the sheet redraw before git blocks the main thread.
        self.plugin.schedule_push(self)

    def performPush(self):
        ok, out = self.repo.push()
        if ok:
            url = self.repo.remote_url()
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

    # Getting somewhere to push to

    def publishCallback(self, sender):
        """Create this repository on GitHub and push it there."""
        if not find_gh():
            self.set_status(
                Glyphs.localize(
                    {
                        "en": "The GitHub CLI (gh) is not installed. Install "
                        "it with “brew install gh”, then run “gh auth login” "
                        "once in the Terminal.",
                        "de": "Das GitHub-CLI (gh) ist nicht installiert. "
                        "Installiere es mit „brew install gh“ und führe "
                        "einmal „gh auth login“ im Terminal aus.",
                    }
                )
            )
            return

        account = self.repo.account()
        if not account:
            self.set_status(
                Glyphs.localize(
                    {
                        "en": "Not signed in to GitHub. Run “gh auth login” "
                        "once in the Terminal.",
                        "de": "Nicht bei GitHub angemeldet. Führe einmal "
                        "„gh auth login“ im Terminal aus.",
                    }
                )
            )
            return

        suggestion = github_slug(self.repo.name())
        slug = f"{account}/{suggestion}"

        # Creating a repository is visible to other people, so always ask,
        # and let the name and the owner be edited before it happens.
        alert = NSAlert.alloc().init()
        alert.setMessageText_(
            Glyphs.localize(
                {"en": "Publish to GitHub", "de": "Auf GitHub anlegen"}
            )
        )
        alert.setInformativeText_(
            Glyphs.localize(
                {
                    "en": "A repository is created and everything committed "
                    "so far is pushed to it. Change the owner before the "
                    "slash to put it in an organisation.",
                    "de": "Es wird ein Repository angelegt und alles bisher "
                    "Committete dorthin gepusht. Ändere den Namen vor dem "
                    "Schrägstrich für eine Organisation.",
                }
            )
        )
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 24))
        field.setStringValue_(slug)
        alert.setAccessoryView_(field)
        alert.addButtonWithTitle_(
            Glyphs.localize({"en": "Create Private", "de": "Privat anlegen"})
        )
        alert.addButtonWithTitle_(
            Glyphs.localize({"en": "Create Public", "de": "Öffentlich anlegen"})
        )
        alert.addButtonWithTitle_(
            Glyphs.localize({"en": "Cancel", "de": "Abbrechen"})
        )

        choice = alert.runModal()
        if choice not in (
            NSAlertFirstButtonReturn,
            NSAlertFirstButtonReturn + 1,
        ):
            return
        private = choice == NSAlertFirstButtonReturn
        slug = str(field.stringValue()).strip()
        if not slug:
            return

        self.w.publishButton.enable(False)
        self.w.chooseFolderButton.enable(False)
        self.set_status(
            Glyphs.localize(
                {
                    "en": f"Creating {slug} on GitHub…",
                    "de": f"Lege {slug} auf GitHub an…",
                }
            )
        )
        self.pending_publish = (slug, private)
        # Let the sheet redraw before the network call blocks the main thread.
        self.plugin.schedule_publish(self)

    def performPublish(self):
        slug, private = self.pending_publish
        ok, out = self.repo.publish(slug, private)

        self.w.publishButton.enable(True)
        self.w.chooseFolderButton.enable(True)
        if not ok:
            self.set_status(f"Could not publish: {out}")
            self.reload()
            return

        self.reload()
        url = self.repo.remote_url() or slug
        self.set_status(
            Glyphs.localize(
                {"en": f"Published to {url}", "de": f"Angelegt: {url}"}
            )
        )

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
        root = self.repo.root()
        if root:
            panel.setDirectoryURL_(
                NSURL.fileURLWithPath_(os.path.dirname(root))
            )

        if panel.runModal() != NSModalResponseOK:
            return

        chosen = str(panel.URLs()[0].path())
        target, error = self.repo.prepare_folder(chosen)
        if error:
            self.set_status(error)
            return

        ok, out = self.repo.set_remote(target)
        if not ok:
            self.set_status(f"Could not set the remote: {out}")
            return

        self.reload()
        self.set_status(
            Glyphs.localize(
                {
                    "en": f"This font now pushes to {target}",
                    "de": f"Diese Schrift pusht jetzt nach {target}",
                }
            )
        )
