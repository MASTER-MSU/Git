from __future__ import absolute_import, unicode_literals, print_function, division

import sublime
import sublime_plugin
import os
import re
from . import GitTextCommand, GitWindowCommand, do_when, goto_xy, git_root, get_open_folder_from_window


class GitDiff (object):
    def run(self, edit=None, ignore_whitespace=False):
        self.ignore_whitespace = ignore_whitespace
        self.edit = edit
        s = sublime.load_settings("Git.sublime-settings")

        # stage untracked files as empty files so they can be seen on the diff
        if s.get('diff_untracked_files'):
            self.stage_untracked_files()
        else:
            self.continue_diff(None)

    def continue_diff(self, result):
        command = ['git', 'diff', '--no-color']
        if self.ignore_whitespace:
            command.extend(('--ignore-all-space', '--ignore-blank-lines'))
        command.extend(('--', self.get_file_name()))
        self.run_command(command, self.diff_done)

    def diff_done(self, result):
        if not result.strip():
            self.panel("No output")
            return
        s = sublime.load_settings("Git.sublime-settings")
        syntax = s.get("diff_syntax", "Packages/Diff/Diff.tmLanguage")
        if s.get('diff_panel'):
            self.panel(result, syntax=syntax)
        else:
            self.scratch(result, title="Git Diff", syntax=syntax)
        self.reset_untracked_files()

    # obtain the modified files list
    def stage_untracked_files(self):
        untracked_files_command = ['git', 'status', '-uall', '--porcelain']
        self.run_command(untracked_files_command, self.stage_untracked_files_result)

    # obtain the untracked files list and stage them
    def stage_untracked_files_result(self, result):
        # filter for untracked files
        lines = result.rstrip().split('\n')
        self.empty_stages = [x[3:] for x in lines if x.startswith('??')]

        if len(self.empty_stages) > 0:
            command = ['git', 'add', '.', '-N']
            self.run_command(command, self.continue_diff, show_status=False)

    # reset the empty staged files to their original untracked status
    def reset_untracked_files(self):
        if len(self.empty_stages) > 0:
            reset_empty_stages_command = ['git', 'reset', '--quiet', '--'] + self.empty_stages
            self.run_command(reset_empty_stages_command, show_status=False)



class GitDiffCommit (object):
    def run(self, edit=None, ignore_whitespace=False):
        command = ['git', 'diff', '--cached', '--no-color']
        if ignore_whitespace:
            command.extend(('--ignore-all-space', '--ignore-blank-lines'))
        self.run_command(command, self.diff_done)

    def diff_done(self, result):
        if not result.strip():
            self.panel("No output")
            return
        s = sublime.load_settings("Git.sublime-settings")
        syntax = s.get("diff_syntax", "Packages/Diff/Diff.tmLanguage")
        self.scratch(result, title="Git Diff", syntax=syntax)


class GitDiffCommand(GitDiff, GitTextCommand):
    pass


class GitDiffAllCommand(GitDiff, GitWindowCommand):
    pass


class GitDiffCommitCommand(GitDiffCommit, GitWindowCommand):
    pass


class GitGotoDiff(sublime_plugin.TextCommand):
    def __init__(self, view):
        self.view = view

    def run(self, edit):
        v = self.view
        view_scope_name = v.scope_name(v.sel()[0].a)
        scope_markup_inserted = ("markup.inserted.diff" in view_scope_name)
        scope_markup_deleted = ("markup.deleted.diff" in view_scope_name)

        if not scope_markup_inserted and not scope_markup_deleted:
            return

        beg = v.sel()[0].a          # Current position in selection
        pt = v.line(beg).a          # First position in the current diff line
        self.column = beg - pt - 1  # The current column (-1 because the first char in diff file)

        self.file_name = None
        hunk_line = None
        line_offset = 0

        while pt > 0:
            line = v.line(pt)
            lineContent = v.substr(line)
            if lineContent.startswith("@@"):
                if not hunk_line:
                    hunk_line = lineContent
            elif lineContent.startswith("+++ b/"):
                self.file_name = v.substr(sublime.Region(line.a + 6, line.b)).strip()
                break
            elif not hunk_line and not lineContent.startswith("-"):
                line_offset = line_offset + 1

            pt = v.line(pt - 1).a

        hunk = re.match(r"^@@ -(\d+)(,(\d+))? \+(\d+)(,(\d+))? @@.*", hunk_line)
        if not hunk:
            sublime.status_message("No hunk info")
            return

        hunk_start_line = hunk.group(4)
        self.goto_line = int(hunk_start_line) + line_offset - 1

        git_root_dir = v.settings().get("git_root_dir")
        # See if we can get the git root directory if we haven't saved it yet
        if not git_root_dir:
            working_dir = get_open_folder_from_window(v.window())
            git_root_dir = git_root(working_dir) if working_dir else None

        # Sanity check and see if the file we're going to try to open even
        # exists. If it does not, prompt the user for the correct base directory
        # to use for their diff.
        full_path_file_name = self.file_name
        if git_root_dir:
            full_path_file_name = os.path.join(git_root_dir, self.file_name)
        else:
            git_root_dir = ""

        if not os.path.isfile(full_path_file_name):
            caption = "Enter base directory for file '%s':" % self.file_name
            v.window().show_input_panel(caption,
                                        git_root_dir,
                                        self.on_path_confirmed,
                                        None,
                                        None)
        else:
            self.on_path_confirmed(git_root_dir)

    def on_path_confirmed(self, git_root_dir):
        v = self.view
        old_git_root_dir = v.settings().get("git_root_dir")

        # If the user provided a new git_root_dir, save it in the view settings
        # so they only have to fix it once
        if old_git_root_dir != git_root_dir:
            v.settings().set("git_root_dir", git_root_dir)

        full_path_file_name = os.path.join(git_root_dir, self.file_name)

        new_view = v.window().open_file(full_path_file_name)
        do_when(lambda: not new_view.is_loading(),
                lambda: goto_xy(new_view, self.goto_line, self.column))
