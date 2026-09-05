#!/usr/bin/env python3
"""Public dashboard: no private names, no local chrome, grid/feed views."""

import unittest
from unittest import mock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import github_repos as gr
import generate_dashboard as gd


def _entry(name, *, private=False, fork=False, catalogue=None, homepage=""):
    return {
        "name": name,
        "private": private,
        "fork": fork,
        "url": f"https://github.com/kylemath/{name}",
        "clone_url": f"https://github.com/kylemath/{name}.git",
        "description": f"{name} desc",
        "pushedAt": "2026-01-01T00:00:00Z",
        "default_branch": "main",
        "homepage": homepage,
        "catalogue": catalogue,
        "screenshot": None,
        "language": "Python",
        "topics": [],
    }


class PublicProjectsTest(unittest.TestCase):
    def test_skips_private_and_forks(self):
        cache = {
            "kylemath/pub": _entry("pub", catalogue={"title": "Pub", "demoUrl": "https://demo.example"}),
            "kylemath/priv": _entry("priv", private=True),
            "kylemath/forked": _entry("forked", fork=True),
        }
        projects = gr._projects_from_entries(
            cache, local_remotes=set(), include_forks=False, only_public=True)
        self.assertEqual([p["id"] for p in projects], ["pub"])
        self.assertEqual(projects[0]["homepage"], "https://demo.example")
        self.assertEqual(projects[0]["html_url"], "https://github.com/kylemath/pub")

    def test_cache_from_repos_json_skips_private(self):
        cache = {
            "kylemath/ok": _entry("ok"),
            "kylemath/secret": _entry("secret", private=True),
        }
        from_file = {
            "kylemath/ok": {
                "name": "ok", "full": "kylemath/ok", "private": False,
                "url": "https://github.com/kylemath/ok",
                "clone_url": "https://github.com/kylemath/ok.git",
                "description": "visible", "pushedAt": "", "updatedAt": None,
                "default_branch": "main", "homepage": "", "fork": False,
                "language": None, "topics": [], "catalogue": None, "screenshot": None,
            }
        }
        projects = gr._projects_from_entries(
            from_file, local_remotes=set(), include_forks=False, only_public=True)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["id"], "ok")
        self.assertNotIn("secret", str(projects))


class PublicHtmlTest(unittest.TestCase):
    def setUp(self):
        self._prev = gd.PUBLIC_MODE
        gd.PUBLIC_MODE = True
        self.project = gr._projects_from_entries(
            {"kylemath/pub": _entry(
                "pub",
                catalogue={"title": "Pub", "oneLiner": "A public repo",
                           "demoUrl": "https://demo.example"},
            )},
            local_remotes=set(), include_forks=False, only_public=True,
        )[0]

    def tearDown(self):
        gd.PUBLIC_MODE = self._prev

    def test_open_url_prefers_demo(self):
        self.assertEqual(gd.public_open_url(self.project), "https://demo.example")

    def test_card_actions_omit_clone(self):
        html = gd.github_card_open_actions(self.project)
        self.assertNotIn("cloneRepo", html)
        self.assertIn("openGithub", html)

    def test_page_hides_local_chrome(self):
        with mock.patch.object(gd.github_repos, "load_public_projects",
                               return_value=[self.project]):
            page = gd.generate_html([])
        self.assertIn("Kyle Mathewson", page)
        self.assertIn("switchView('grid')", page)
        self.assertIn("switchView('feed')", page)
        self.assertIn("const PUBLIC_PAGE = true", page)
        self.assertNotIn("⏹ Stop server", page)
        self.assertNotIn("＋ New project", page)
        self.assertNotIn('id="portsBtn"', page)
        self.assertNotIn('id="refreshBtn"', page)
        self.assertNotIn('onclick="cloneRepo', page)
        self.assertNotIn("/Users/", page)
        blocking, _warnings = gd._check_public_leaks(page)
        self.assertEqual(blocking, [])

    def test_screenshot_is_hotlinked_not_embedded(self):
        self.project["has_catalogue"] = True
        self.project["screenshot_path"] = "/Users/someone/secret.png"
        src = gd.resolve_screenshot_src(self.project)
        self.assertTrue(src is None or src.startswith("http"))
        self.assertNotIn("data:image", src or "")


if __name__ == "__main__":
    unittest.main()
