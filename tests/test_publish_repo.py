#!/usr/bin/env python3
"""Unit tests for publish_repo helpers (no GitHub network)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish_repo as pr


class PublishRepoHelpersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Pretend this folder lives under home so path checks can be tested
        # separately; helpers that only need a dir use self.root.

    def tearDown(self):
        self.tmp.cleanup()

    def test_detect_static(self):
        (self.root / 'index.html').write_text('<h1>hi</h1>')
        kind = pr.detect_kind(str(self.root))
        self.assertTrue(kind['static'])
        self.assertFalse(kind['backend'])

    def test_detect_python_backend(self):
        (self.root / 'app.py').write_text('import flask\napp = flask.Flask(__name__)\n')
        kind = pr.detect_kind(str(self.root))
        self.assertTrue(kind['backend'])
        self.assertIn('Python', kind['backend_type'])

    def test_recommended_defaults_static_is_public_pages(self):
        (self.root / 'index.html').write_text('<h1>hi</h1>')
        d = pr.recommended_defaults(str(self.root))
        self.assertEqual(d['visibility'], 'public')
        self.assertTrue(d['pages'])
        self.assertFalse(d['is_repo'])
        self.assertFalse(d['has_remote'])

    def test_recommended_defaults_backend_is_private_no_pages(self):
        (self.root / 'requirements.txt').write_text('fastapi\nuvicorn\n')
        d = pr.recommended_defaults(str(self.root))
        self.assertEqual(d['visibility'], 'private')
        self.assertFalse(d['pages'])

    def test_ensure_gitignore_readme_cursor(self):
        path = str(self.root)
        self.assertTrue(pr.ensure_gitignore(path))
        self.assertFalse(pr.ensure_gitignore(path))
        self.assertIn('node_modules/', (self.root / '.gitignore').read_text())
        self.assertTrue(pr.ensure_readme(path, 'magicSquare', 'A puzzle.'))
        text = (self.root / 'README.md').read_text()
        self.assertIn('# Magic Square', text)
        self.assertIn('A puzzle.', text)
        self.assertFalse(pr.ensure_readme(path))
        self.assertTrue(pr.ensure_cursor_dir(path))
        self.assertTrue((self.root / '.cursor' / '.gitkeep').is_file())
        self.assertFalse(pr.ensure_cursor_dir(path))

    def test_auto_ignore_secrets_and_large_not_json(self):
        (self.root / '.env').write_text('SECRET=1\n')
        (self.root / 'catalogue.json').write_text('{}')
        (self.root / 'notes.json').write_text('{"ok": true}')
        big = self.root / 'blob.bin'
        big.write_bytes(b'x' * (pr.LARGE_FILE_BYTES + 1))
        added = pr.auto_ignore_secrets(str(self.root))
        self.assertIn('.env', added)
        self.assertIn('blob.bin', added)
        self.assertNotIn('catalogue.json', added)
        self.assertNotIn('notes.json', added)
        gi = (self.root / '.gitignore').read_text()
        self.assertIn('.env', gi)

    def test_embed_screenshot_and_pages_link(self):
        (self.root / 'README.md').write_text('# Title\n\nHello.\n')
        (self.root / 'screenshot.png').write_bytes(b'\x89PNG')
        self.assertTrue(pr.embed_screenshot_in_readme(str(self.root)))
        self.assertFalse(pr.embed_screenshot_in_readme(str(self.root)))
        text = (self.root / 'README.md').read_text()
        self.assertIn('screenshot.png', text)
        url = 'https://example.github.io/Title'
        self.assertTrue(pr.add_pages_link_to_readme(str(self.root), url))
        self.assertFalse(pr.add_pages_link_to_readme(str(self.root), url))
        self.assertIn('Live Demo', (self.root / 'README.md').read_text())

    def test_sanitize_and_suggested_repo_name(self):
        self.assertEqual(pr.sanitize_repo_name('Magic Square'), 'Magic-Square')
        self.assertEqual(pr.sanitize_repo_name('  foo/bar!!  '), 'foobar')
        (self.root / 'catalogue.json').write_text(json.dumps({
            'id': 'prettyRepo', 'title': 'Pretty Repo',
        }))
        self.assertEqual(pr.suggested_repo_name(str(self.root)), 'prettyRepo')

    def test_pretty_title(self):
        self.assertEqual(pr.pretty_title('magicSquare'), 'Magic Square')
        self.assertEqual(pr.pretty_title('my-cool_app'), 'My Cool App')

    def test_parse_github_remote(self):
        self.assertEqual(
            pr.parse_github_remote('git@github.com:kylemath/gitBash.git'),
            ('kylemath', 'gitBash'),
        )
        self.assertEqual(
            pr.parse_github_remote('https://github.com/kylemath/cursor-launcher'),
            ('kylemath', 'cursor-launcher'),
        )

    def test_patch_catalogue_after_publish(self):
        (self.root / 'catalogue.json').write_text(json.dumps({
            'id': 'demo', 'title': 'Demo', 'status': 'active',
        }))
        (self.root / 'screenshot.png').write_bytes(b'\x89PNG')
        pr._patch_catalogue_after_publish(str(self.root), 'https://x.github.io/demo')
        data = json.loads((self.root / 'catalogue.json').read_text())
        self.assertEqual(data['screenshot'], './screenshot.png')
        self.assertEqual(data['demoUrl'], 'https://x.github.io/demo')
        self.assertEqual(data['status'], 'published')

    def test_allowed_path_rejects_home_and_system(self):
        self.assertFalse(pr.is_allowed_project_path(str(Path.home())))
        self.assertFalse(pr.is_allowed_project_path(str(Path.home() / 'Library')))
        self.assertFalse(pr.is_allowed_project_path('/tmp'))

    def test_find_gh_without_path_uses_candidates(self):
        fake_dir = self.root / 'bin'
        fake_dir.mkdir()
        fake = fake_dir / 'gh'
        fake.write_text('#!/bin/sh\n')
        fake.chmod(0o755)
        pr._GH_BIN = None
        try:
            with mock.patch.object(pr, 'ensure_login_path'):
                with mock.patch.object(pr.shutil, 'which', return_value=None):
                    with mock.patch.object(pr, 'GH_CANDIDATES', (str(fake),)):
                        found = pr.find_gh()
        finally:
            pr._GH_BIN = None
        self.assertEqual(found, str(fake))

    def test_find_gh_on_bare_macos_path(self):
        if not any(os.path.isfile(p) and os.access(p, os.X_OK) for p in pr.GH_CANDIDATES):
            self.skipTest('no Homebrew gh on this machine')
        pr._GH_BIN = None
        old = os.environ.get('PATH', '')
        os.environ['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
        try:
            found = pr.find_gh()
            status = pr.gh_status()
        finally:
            os.environ['PATH'] = old
            pr._GH_BIN = None
        self.assertTrue(found.endswith('/gh'))
        self.assertTrue(status.get('ok'), status)

    def test_cli_parser_defaults_and_flags(self):
        parser = pr.build_parser()
        ns = parser.parse_args([])
        self.assertEqual(ns.path, '.')
        self.assertFalse(ns.preview)
        self.assertFalse(ns.public)
        self.assertFalse(ns.private)
        self.assertFalse(ns.pages)
        self.assertFalse(ns.no_pages)
        ns = parser.parse_args(['~/proj', '--public', '--pages', '--name', 'Demo', '-m', 'init'])
        self.assertEqual(ns.path, '~/proj')
        self.assertTrue(ns.public)
        self.assertTrue(ns.pages)
        self.assertEqual(ns.name, 'Demo')
        self.assertEqual(ns.message, 'init')

    def test_resolve_cli_options_overrides_and_defaults(self):
        defaults = {'visibility': 'private', 'pages': False, 'repo_name': 'folder'}
        parser = pr.build_parser()
        opts = pr.resolve_cli_options(parser.parse_args([]), defaults)
        self.assertEqual(opts['visibility'], 'private')
        self.assertFalse(opts['pages'])
        self.assertEqual(opts['repo_name'], 'folder')
        opts = pr.resolve_cli_options(
            parser.parse_args(['--public', '--pages', '--name', 'X']),
            defaults,
        )
        self.assertEqual(opts['visibility'], 'public')
        self.assertTrue(opts['pages'])
        self.assertEqual(opts['repo_name'], 'X')
        opts = pr.resolve_cli_options(
            parser.parse_args(['--private', '--no-pages']),
            {'visibility': 'public', 'pages': True, 'repo_name': 'folder'},
        )
        self.assertEqual(opts['visibility'], 'private')
        self.assertFalse(opts['pages'])


if __name__ == '__main__':
    unittest.main()
