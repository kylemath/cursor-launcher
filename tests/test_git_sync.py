#!/usr/bin/env python3
"""Unit tests for git_sync (local git only, no remotes)."""

import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import git_sync as gs


def _git(path, *args):
    subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)


class GitSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _git(self.root, 'init', '-b', 'main')
        _git(self.root, 'config', 'user.email', 'test@example.com')
        _git(self.root, 'config', 'user.name', 'Test')
        (self.root / 'README.md').write_text('# hi\n')
        _git(self.root, 'add', 'README.md')
        _git(self.root, 'commit', '-m', 'init')

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_porcelain(self):
        self.assertEqual(
            gs.parse_porcelain_line(' M catalogue.json')['kind'], 'changed')
        self.assertEqual(
            gs.parse_porcelain_line('?? screenshot.png')['path'], 'screenshot.png')
        self.assertEqual(
            gs.parse_porcelain_line('R  old.txt -> new.txt')['path'], 'new.txt')
        self.assertIsNone(gs.parse_porcelain_line(''))

    def test_suggest_message(self):
        self.assertEqual(
            gs.suggest_commit_message(['catalogue.json', 'screenshot.png']),
            'Add catalogue and screenshot')
        self.assertEqual(gs.suggest_commit_message(['notes.md']), 'Update notes.md')

    def test_working_tree_and_commit_without_push(self):
        (self.root / 'catalogue.json').write_text('{"id":"x"}\n')
        (self.root / 'screenshot.png').write_bytes(b'\x89PNG')
        (self.root / '.DS_Store').write_bytes(b'x')
        tree = gs.working_tree(str(self.root))
        self.assertEqual(tree['status'], 'ok')
        self.assertTrue(tree['dirty'])
        paths = {f['path'] for f in tree['files']}
        self.assertIn('catalogue.json', paths)
        self.assertIn('screenshot.png', paths)
        self.assertNotIn('.DS_Store', paths)
        self.assertEqual(tree['suggested_message'], 'Add catalogue and screenshot')

        result = gs.commit_and_push(
            str(self.root),
            message=None,
            include_untracked=True,
            push=False,
        )
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result['committed'])
        self.assertFalse(result['pushed'])
        after = gs.working_tree(str(self.root))
        self.assertFalse(after['dirty'])

    def test_selective_add_skips_untracked_when_disabled(self):
        (self.root / 'README.md').write_text('# changed\n')
        (self.root / 'secret.txt').write_text('nope\n')
        result = gs.commit_and_push(
            str(self.root),
            message='only tracked',
            include_untracked=False,
            push=False,
        )
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['files'], ['README.md'])
        tree = gs.working_tree(str(self.root))
        self.assertEqual([f['path'] for f in tree['files']], ['secret.txt'])

    def test_nothing_to_do(self):
        result = gs.commit_and_push(str(self.root), push=False)
        self.assertEqual(result['status'], 'error')
        self.assertIn('Nothing', result['message'])


if __name__ == '__main__':
    unittest.main()
