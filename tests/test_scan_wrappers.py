#!/usr/bin/env python3
"""Non-repo folders that contain git repos expand to those repos."""

import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate_dashboard as gd


def _git(path, *args):
    subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)


class WrapperScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _repo(self, name):
        path = self.root / name
        path.mkdir()
        _git(path, 'init', '-b', 'main')
        return path

    def test_wrapper_expands_to_child_repos_only(self):
        wrapper = self.root / 'Teaching'
        wrapper.mkdir()
        a = self._repo('Teaching/Psych275Alberta')
        b = self._repo('Teaching/psych275-textbook')
        (wrapper / 'notes.bundle').write_text('not a repo')
        (wrapper / 'loose-notes').mkdir()
        names = [p.name for p in gd.immediate_git_repos(wrapper)]
        self.assertEqual(names, ['Psych275Alberta', 'psych275-textbook'])
        self.assertEqual(gd.folders_to_scan(wrapper), [a, b])

    def test_real_repo_is_not_expanded(self):
        repo = self._repo('cursor-launcher')
        (repo / 'nested').mkdir()
        _git(repo / 'nested', 'init', '-b', 'main')
        self.assertEqual(gd.immediate_git_repos(repo), [])
        self.assertEqual(gd.folders_to_scan(repo), [repo])

    def test_plain_folder_stays_one_card(self):
        plain = self.root / 'notes'
        plain.mkdir()
        (plain / 'a.txt').write_text('hi')
        self.assertEqual(gd.immediate_git_repos(plain), [])
        self.assertEqual(gd.folders_to_scan(plain), [plain])


if __name__ == '__main__':
    unittest.main()
