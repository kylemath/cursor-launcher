#!/usr/bin/env python3
"""Unit tests for publish_repo helpers (no GitHub network)."""

import json
import tempfile
import unittest
from pathlib import Path
import sys

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


if __name__ == '__main__':
    unittest.main()
