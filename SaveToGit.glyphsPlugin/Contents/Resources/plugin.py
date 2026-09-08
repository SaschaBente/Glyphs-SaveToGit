import objc

import os
import subprocess
import sys

from pathlib import Path
from re import compile, sub

from AppKit import NSClassFromString, NSMenuItem
from GlyphsApp import FILE_MENU, Glyphs, Message
from GlyphsApp.plugins import GeneralPlugin

# The sheet lives next to this file, so make sure it can be imported.
_RESOURCES = os.path.dirname(os.path.abspath(__file__))
if _RESOURCES not in sys.path:
    sys.path.insert(0, _RESOURCES)

try:
    from gitsheet import CommitSheet, PushSheet, Repo, is_git_repo
except ImportError as e:
    # vanilla is missing: keep the plain "Save to Git" command working.
    CommitSheet = None
    PushSheet = None
    Repo = None
    IMPORT_ERROR = e

    def is_git_repo(path):
        return True


GSCompareFonts = NSClassFromString("GSCompareFonts")

GLYPHNAME_REGEX = compile(r"(?<=[A-Z])(_)")


class SaveToGit(GeneralPlugin):
    @objc.python_method
    def settings(self):
        self.name = Glyphs.localize(
            {"en": "Save to Git", "de": "In Git sichern"}
        )
        # The same command, but with a sheet to write the commit message in.
        self.sheet_name = Glyphs.localize(
            {"en": "Commit to Git…", "de": "In Git committen…"}
        )
        # Pushing is its own command, with its own sheet.
        self.push_name = Glyphs.localize(
            {"en": "Push to GitHub…", "de": "Zu GitHub pushen…"}
        )
        self.sheet = None

    @objc.python_method
    def start(self):
        # Set menu item so that it will call the validateMenuItem_ method
        saveAndCommitMenuItem = NSMenuItem.alloc().init()
        saveAndCommitMenuItem.setTitle_(self.name)
        saveAndCommitMenuItem.setTarget_(self)
        saveAndCommitMenuItem.setAction_(self.saveAndCommit_)
        Glyphs.menu[FILE_MENU].append(saveAndCommitMenuItem)

        openSheetMenuItem = NSMenuItem.alloc().init()
        openSheetMenuItem.setTitle_(self.sheet_name)
        openSheetMenuItem.setTarget_(self)
        openSheetMenuItem.setAction_(self.openCommitSheet_)
        Glyphs.menu[FILE_MENU].append(openSheetMenuItem)

        pushMenuItem = NSMenuItem.alloc().init()
        pushMenuItem.setTitle_(self.push_name)
        pushMenuItem.setTarget_(self)
        pushMenuItem.setAction_(self.openPushSheet_)
        Glyphs.menu[FILE_MENU].append(pushMenuItem)

    def validateMenuItem_(self, menuItem):
        return Glyphs.font is not None

    @objc.python_method
    def run_git_cmd(self, args, working_dir=None):
        result = None
        # result = subprocess.run(cmd, capture_output=True)
        try:
            result = subprocess.check_output(
                args, stderr=subprocess.STDOUT, cwd=working_dir, shell=False
            )
        except subprocess.CalledProcessError as e:
            # Glyphs.showNotification(self.name, f"Error: {e.output}")
            print(f"Git error: {e.output}")
        return result

    @objc.python_method
    def build_commit_msg(self, old_font, new_font):
        msg = f"Update {new_font.familyName} {new_font.masters[0].name}"
        glyphs = []
        for name in new_font.glyphs.keys():
            # Glyph has been added
            if name not in old_font.glyphs:
                glyphs.append(name)
                continue

            # Glyph comparison
            old_glyph = old_font.glyphs[name]
            new_glyph = new_font.glyphs[name]
            glyph_cmp = GSCompareFonts.compareGlyph_andGlyph_(
                old_font.glyphs[name], new_font.glyphs[name]
            )
            if glyph_cmp:
                glyphs.append(name)
                continue

            # Layer comparison
            num_old_layers = len(old_glyph.layers)
            num_new_layers = len(new_glyph.layers)
            if num_old_layers != num_new_layers:
                continue
            for i in range(num_old_layers):
                layer_cmp = GSCompareFonts.compareLayer_andLayer_(
                    old_glyph.layers[i], new_glyph.layers[i]
                )
                if layer_cmp:
                    glyphs.append(name)
        if glyphs:
            msg += ": " + ", ".join(sorted(set(glyphs)))
        return msg

    @objc.python_method
    def quick_message(self, font):
        """A commit message that costs nothing to work out."""
        try:
            return f"Update {font.familyName} {font.masters[0].name}"
        except (AttributeError, IndexError):
            return ""

    @objc.python_method
    def save_font(self, font):
        """Save the font, unless it has nothing to save.

        A large font takes a noticeable moment to write, so it is worth
        asking the document whether anything changed first.
        """
        try:
            document = font.parent
            if document is not None and not document.isDocumentEdited():
                return
        except AttributeError:
            pass
        font.save(font.filepath)

    @objc.python_method
    def describe_changes(self, font):
        """Work out which glyphs changed, for the commit message.

        This is the slow part: it opens the previous version of the font and
        compares every glyph, so it only runs once the sheet is on screen.
        """
        font_path = font.filepath
        if font_path is None:
            return None

        fontdir = Path(font_path).parent
        fontfile = Path(font_path).name
        # The package format is compared through git, which can only see
        # what has been written to disk.
        self.save_font(font)

        if font_path.endswith(".glyphspackage"):
            return self._comparePackage(font, fontfile, fontdir)
        return self._compareAllInOne(font, fontfile, fontdir)

    @objc.python_method
    def schedule_describe(self, sheet):
        """Describe the changes once the sheet has been drawn."""
        self.sheet = sheet
        try:
            self.performSelector_withObject_afterDelay_(
                self.performDescribe_, None, 0.05
            )
        except Exception:
            sheet.performDescribe()

    def performDescribe_(self, sender):
        if self.sheet is not None:
            self.sheet.performDescribe()

    @objc.python_method
    def saveAndDescribe(self):
        """Save the current font and describe its changes.

        Returns (font, fontdir, fontfile, msg), where msg is the suggested
        commit message, or None when the changes could not be determined.
        Returns None altogether when there is no font to save.
        """
        font = Glyphs.font
        if font is None:
            return None

        font_path = font.filepath
        if font_path is None:
            Message(
                message=(
                    "Please save your Glyphs file once before using "
                    "Save to Git."
                ),
                title=self.name,
            )
            return None

        fontdir = Path(font_path).parent
        fontfile = Path(font_path).name
        font.save(font_path)

        # Compare with last revision

        if font_path.endswith(".glyphspackage"):
            # print(font_path, "is package format")
            msg = self._comparePackage(font, fontfile, fontdir)
        else:
            # print(font_path, "is all in one format")
            msg = self._compareAllInOne(font, fontfile, fontdir)

        return font, fontdir, fontfile, msg

    def saveAndCommit_(self, sender):
        prepared = self.saveAndDescribe()
        if prepared is None:
            return
        font, fontdir, fontfile, msg = prepared

        if msg is None:
            Message(
                message=(
                    f"Could not determine changes for {font.familyName}. "
                    "Committing to the git repository anyway."
                ),
                title=self.name,
            )
            msg = "Unspecified changes"

        # Add changed file to index
        self.run_git_cmd(["git", "add", fontfile], fontdir)

        # Commit changes
        self.run_git_cmd(["git", "commit", "-m", msg], fontdir)
        Glyphs.showNotification(self.name, msg)

    # "Commit to Git…": the same thing, but with a sheet

    @objc.python_method
    def sheets_available(self, title):
        """Whether the sheets can be shown, complaining if they cannot."""
        if CommitSheet is not None:
            return True
        Message(
            message=(
                "The sheets need the vanilla module, which could not be "
                f"imported: {IMPORT_ERROR}\nYou can install it from "
                "Window > Plugin Manager > Modules."
            ),
            title=title,
        )
        return False

    @objc.python_method
    def repo_for_font(self, font, title):
        """The repository a saved font is in, complaining if there is none."""
        font_path = font.filepath
        fontdir = Path(font_path).parent
        fontfile = Path(font_path).name
        if not is_git_repo(fontdir):
            Message(
                message=(
                    f"“{fontfile}” is not inside a git repository, so there "
                    "is nothing to commit to."
                ),
                title=title,
            )
            return None
        return Repo(fontdir, fontfile)

    def openCommitSheet_(self, sender):
        if not self.sheets_available(self.sheet_name):
            return

        font = Glyphs.font
        if font is None:
            return
        if font.filepath is None:
            Message(
                message=(
                    "Please save your Glyphs file once before using "
                    "Save to Git."
                ),
                title=self.sheet_name,
            )
            return

        repo = self.repo_for_font(font, self.sheet_name)
        if repo is None:
            return

        # Show the sheet at once with a message that costs nothing. Saving
        # the font and working out which glyphs changed can take seconds on
        # a large family, and both happen once the sheet is up.
        self.sheet = CommitSheet(self, font, repo, self.quick_message(font))
        self.sheet.open()

    # "Push to GitHub…": its own command, its own sheet

    def openPushSheet_(self, sender):
        if not self.sheets_available(self.push_name):
            return

        font = Glyphs.font
        if font is None:
            return
        if font.filepath is None:
            Message(
                message=(
                    "Please save your Glyphs file once before using "
                    "Save to Git."
                ),
                title=self.push_name,
            )
            return

        repo = self.repo_for_font(font, self.push_name)
        if repo is None:
            return

        # Pushing neither saves nor commits, so the font is left alone.
        self.sheet = PushSheet(self, font, repo)
        self.sheet.open()

    @objc.python_method
    def parent_window(self, font):
        """The document window to attach the sheet to, if there is one."""
        try:
            return font.parent.windowController().window()
        except Exception as e:
            print(f"{self.name}: no window to attach the sheet to ({e})")
            return None

    @objc.python_method
    def schedule_push(self, sheet):
        """Push after a moment, so the sheet can redraw first.

        git push blocks the main thread, and the sheet should have shown its
        "Pushing…" status before that happens.
        """
        self.sheet = sheet
        try:
            self.performSelector_withObject_afterDelay_(
                self.performPush_, None, 0.05
            )
        except Exception:
            sheet.performPush()

    def performPush_(self, sender):
        if self.sheet is not None:
            self.sheet.performPush()

    @objc.python_method
    def schedule_publish(self, sheet):
        """Publish after a moment, for the same reason as schedule_push."""
        self.sheet = sheet
        try:
            self.performSelector_withObject_afterDelay_(
                self.performPublish_, None, 0.05
            )
        except Exception:
            sheet.performPublish()

    def performPublish_(self, sender):
        if self.sheet is not None:
            self.sheet.performPublish()

    @objc.python_method
    def _compareAllInOne(self, font, fontfile, fontdir):
        # Get previous version of the file
        msg = None
        old_data = self.run_git_cmd(
            ["git", "show", f"HEAD:./{fontfile}"], fontdir
        )
        if old_data is None:
            # Font probably is new in repository
            msg = f"Add {font.familyName} {font.masters[0].name}"
        else:
            # Save to a temp file and open it for comparison
            tmp_file_path = Path(fontdir) / f".de.kutilek.SaveToGit.{fontfile}"
            with open(tmp_file_path, "wb") as old_file:
                old_file.write(old_data)
            old_font = Glyphs.open(str(tmp_file_path), showInterface=False)
            if old_font is None:
                # glyphspackage format?
                print(f"{self.name}: Something went wrong.")
                print(
                    f"Tried to save a temporary file to '{tmp_file_path}', "
                    "but opening the file again for comparison failed."
                )
            else:
                msg = self.build_commit_msg(old_font, font)
                old_font.close()
            Path.unlink(tmp_file_path, missing_ok=True)
        return msg

    @objc.python_method
    def _comparePackage(self, font, fontfile, fontdir):
        # Show changes
        changes = self.run_git_cmd(
            ["git", "diff", "--name-status", fontfile], fontdir
        )
        if changes is None:
            # Font probably is new in repository
            msg = f"Add {font.familyName} {font.masters[0].name}"
        else:
            msg = f"Update {font.familyName} {font.masters[0].name}"
            changes = changes.decode("utf-8")

            # Find git repo root
            root = self.run_git_cmd(
                ["git", "rev-parse", "--show-toplevel"], fontdir
            )
            root = root.decode("utf-8").strip()

            # Find changed glyphs
            # M       src/Font.glyphspackage/glyphs/A_.glyph
            # etc.
            glyph_paths = [
                line.strip()
                for line in changes.splitlines()
                if "/glyphs/" in line
            ]

            glyphs = []
            for glyph_path in glyph_paths:
                parts = glyph_path.rsplit("/", 1)
                if len(parts) != 2:
                    print("Unhandled status:", parts)
                    continue
                _, filename = parts
                glyphname_esc = filename.rsplit(".", 1)[0]
                glyphname = sub(GLYPHNAME_REGEX, "", glyphname_esc)
                if glyphname:
                    glyphs.append(glyphname)
            if glyphs:
                glyphnames = ", ".join(sorted(set(glyphs)))
                msg += f": {glyphnames}"
        return msg

    @objc.python_method
    def __file__(self):
        """Please leave this method unchanged"""
        return __file__
