from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "dev" / "scripts"

sys.path.insert(0, str(SCRIPTS))

import dev_config  # noqa: E402

SPEC = importlib.util.spec_from_file_location("showcase_badge", SCRIPTS / "showcase_badge.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


VALID_DOC = {
    "version": 1,
    "github": {
        "host": "github.com",
        "account": "KHAEntertainment",
        "pushRepository": "KHAEntertainment/claude-dev-skill",
        "pullRequestRepository": "KHAEntertainment/claude-dev-skill",
        "pushRemote": "origin",
    },
}

SLUG = "KHAEntertainment/claude-dev-skill"
TOKEN = "supersecret-token-value-123"
HEX_ID = "a" * 64
ORIGIN_URL = "https://github.com/KHAEntertainment/claude-dev-skill.git"


def _git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=check, capture_output=True, text=True
    )


def _decide(**overrides):
    params = dict(
        readme_skill_present=True,
        showcase=None,
        host_present=False,
        visibility="public",
        token_present=True,
        greenfield=True,
        slug=SLUG,
    )
    params.update(overrides)
    return MODULE.decide(**params)


class DecideTableTests(unittest.TestCase):
    def test_missing_readme_skill_is_noop_even_with_everything_else(self) -> None:
        decision = _decide(readme_skill_present=False)
        self.assertEqual("noop", decision["action"])
        self.assertEqual("readme_skill_missing", decision["reason"])
        self.assertIn("README skill", decision["detail"])

    def test_recorded_decline_is_noop(self) -> None:
        decision = _decide(showcase={"badge": False})
        self.assertEqual("noop", decision["action"])
        self.assertEqual("declined", decision["reason"])

    def test_recorded_decline_beats_host_match(self) -> None:
        decision = _decide(showcase={"badge": False}, host_present=True)
        self.assertEqual("noop", decision["action"])
        self.assertEqual("declined", decision["reason"])

    def test_hand_removal_when_badge_true_but_host_absent(self) -> None:
        decision = _decide(showcase={"badge": True}, host_present=False)
        self.assertEqual("hand_removal", decision["action"])
        self.assertFalse(decision["record"]["badge"])

    def test_idempotent_when_host_present_and_badge_absent(self) -> None:
        decision = _decide(showcase=None, host_present=True)
        self.assertEqual("noop", decision["action"])
        self.assertEqual("idempotent", decision["reason"])

    def test_unlanded_badge_does_not_read_as_hand_removal(self) -> None:
        # A public "yes" recorded while the docs PR is open, with the badge not
        # yet landed, must resume -- not be mistaken for hand removal.
        decision = _decide(showcase={"badgeApproved": True}, host_present=False)
        self.assertEqual("resume", decision["action"])
        self.assertNotEqual("hand_removal", decision["action"])

    def test_badge_approved_resumes_with_block_and_no_prompt(self) -> None:
        decision = _decide(
            showcase={"badgeApproved": True}, host_present=False, visibility="public"
        )
        self.assertEqual("resume", decision["action"])
        self.assertIn("&project=", decision["block"])
        self.assertNotIn("prompt", decision)
        self.assertTrue(decision["unplaced"])

    def test_badge_approved_is_ignored_when_host_already_present(self) -> None:
        decision = _decide(
            showcase={"badgeApproved": True}, host_present=True, visibility="public"
        )
        self.assertEqual("noop", decision["action"])
        self.assertEqual("idempotent", decision["reason"])

    def test_public_greenfield_defaults_on(self) -> None:
        decision = _decide(visibility="public", greenfield=True, host_present=False)
        self.assertEqual("default_on", decision["action"])
        self.assertEqual("granted", decision["consent"])
        self.assertIn("&project=", decision["block"])
        self.assertIn("svg.khaentertainment.com/badge.svg", decision["block"])
        self.assertIn("svg.khaentertainment.com/go", decision["block"])

    def test_default_on_includes_removal_detail(self) -> None:
        decision = _decide(visibility="public", greenfield=True, host_present=False)
        self.assertEqual("default_on", decision["action"])
        self.assertIn("deleting the one line", decision["detail"])

    def test_public_brownfield_prompts_and_includes_unplaced_block(self) -> None:
        decision = _decide(visibility="public", greenfield=False)
        self.assertEqual("prompt_public", decision["action"])
        self.assertIn("Built with Showrunner", decision["prompt"])
        self.assertIn("&project=", decision["block"])
        self.assertTrue(decision["unplaced"])

    def test_private_no_token_is_noop(self) -> None:
        decision = _decide(visibility="private", token_present=False)
        self.assertEqual("noop", decision["action"])
        self.assertEqual("token_missing", decision["reason"])
        self.assertIn("SHOWRUNNER_REGISTER_TOKEN", decision["detail"])

    def test_undetermined_visibility_treated_as_private(self) -> None:
        decision = _decide(visibility="undetermined", token_present=False)
        self.assertEqual("noop", decision["action"])
        self.assertEqual("token_missing", decision["reason"])

    def test_private_prompts_to_register(self) -> None:
        decision = _decide(visibility="private", token_present=True)
        self.assertEqual("prompt_private", decision["action"])

    def test_registered_but_not_visible_is_noop(self) -> None:
        decision = _decide(
            visibility="private", token_present=True,
            showcase={"registered": True, "privateId": "abcdef1234567890"},
        )
        self.assertEqual("noop", decision["action"])
        self.assertEqual("already_registered", decision["reason"])

    def test_registered_but_not_displayed_returns_p_block(self) -> None:
        decision = _decide(
            visibility="private", token_present=True,
            showcase={"registered": True, "privateId": "abcdef1234567890", "showBadge": True},
        )
        self.assertEqual("registered_not_displayed", decision["action"])
        self.assertIn("?p=abcdef1234567890", decision["block"])
        self.assertNotIn("prompt", decision)
        self.assertTrue(decision["unplaced"])

    def test_registered_not_displayed_without_token_is_noop(self) -> None:
        decision = _decide(
            visibility="private", token_present=False,
            showcase={"registered": True, "privateId": "abcdef1234567890", "showBadge": True},
        )
        self.assertEqual("noop", decision["action"])
        self.assertEqual("token_missing", decision["reason"])

    def test_pending_registration_retries_without_prompt(self) -> None:
        decision = _decide(
            visibility="private", token_present=True,
            showcase={"registerApproved": True},
        )
        self.assertEqual("retry_register", decision["action"])

    def test_pending_registration_without_token_is_noop(self) -> None:
        decision = _decide(
            visibility="private", token_present=False,
            showcase={"registerApproved": True},
        )
        self.assertEqual("noop", decision["action"])
        self.assertEqual("token_missing", decision["reason"])

    def test_private_visible_badge_with_private_id_no_collision_with_hand_removal(self) -> None:
        decision = _decide(
            visibility="private", token_present=True, host_present=True,
            showcase={"registered": True, "privateId": "abcdef1234567890", "badge": True},
        )
        self.assertEqual("idempotent", decision["reason"])
        decision = _decide(
            visibility="private", token_present=True, host_present=False,
            showcase={"registered": True, "privateId": "abcdef1234567890", "badge": True},
        )
        self.assertEqual("hand_removal", decision["action"])


class PromptWordingTests(unittest.TestCase):
    def test_private_prompt_does_not_claim_name_never_sent(self) -> None:
        self.assertNotIn("never sent", MODULE.PROMPT_PRIVATE)
        self.assertNotIn("never leaves", MODULE.PROMPT_PRIVATE)
        self.assertIn("sent once", MODULE.PROMPT_PRIVATE)
        self.assertIn("?project=", MODULE.PROMPT_PRIVATE)

    def test_public_prompt_does_not_claim_registration_or_counting(self) -> None:
        lowered = MODULE.PROMPT_PUBLIC.lower()
        self.assertNotIn("regist", lowered)
        self.assertNotIn("count", lowered)
        self.assertIn("links back", MODULE.PROMPT_PUBLIC)
        self.assertIn("deleting the one line", MODULE.PROMPT_PUBLIC)


class BuildBlockTests(unittest.TestCase):
    def test_public_block_uses_project_and_go_link(self) -> None:
        block = MODULE.build_block(SLUG)
        self.assertIn(f"project={SLUG}", block)
        self.assertNotIn("?p=", block)
        self.assertIn("](https://svg.khaentertainment.com/go)", block)

    def test_private_block_uses_p_on_both_image_and_link(self) -> None:
        block = MODULE.build_block(SLUG, "abcdef1234567890")
        self.assertNotIn("project=", block)
        self.assertIn("badge.svg?theme=midnight&anim=orbit&p=abcdef1234567890", block)
        self.assertIn("](https://svg.khaentertainment.com/go?p=abcdef1234567890)", block)


class ValidateIdTests(unittest.TestCase):
    def test_valid_and_invalid_ids(self) -> None:
        self.assertTrue(MODULE.validate_id("9f2c1a3b4c5d6e7f"))
        self.assertTrue(MODULE.validate_id("a" * 64))
        self.assertFalse(MODULE.validate_id("9f2c"))
        self.assertFalse(MODULE.validate_id("XYZ1"))
        self.assertFalse(MODULE.validate_id("9f2c1a3b4c5d6e7f-"))
        self.assertFalse(MODULE.validate_id(""))


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")
        self.read_args = None

    def read(self, *args) -> bytes:
        self.read_args = args
        return self._body

    def close(self) -> None:
        pass


class _FakeOpener:
    def __init__(self, response):
        self._response = response
        self.opened_url = None
        self.auth_header = None

    def open(self, request, timeout=None):
        self.opened_url = request.full_url if hasattr(request, "full_url") else request.get_full_url()
        self.auth_header = request.get_header("Authorization")
        return self._response


def _real_response_body(status: str = "counted") -> str:
    return json.dumps(
        {"private": True, "counted": True, "status": status, "id": HEX_ID, "count": 3}
    )


class RegisterTests(unittest.TestCase):
    def test_success_returns_hex_id_from_real_shape(self) -> None:
        opener = _FakeOpener(_FakeResponse(_real_response_body("counted")))
        self.assertEqual(HEX_ID, MODULE.register(TOKEN, SLUG, opener=opener))
        self.assertIn("svg.khaentertainment.com/register", opener.opened_url)
        self.assertIn("private=1", opener.opened_url)

    def test_token_is_sent_in_header_not_url(self) -> None:
        opener = _FakeOpener(_FakeResponse(_real_response_body()))
        MODULE.register(TOKEN, SLUG, opener=opener)
        self.assertNotIn(TOKEN, opener.opened_url)
        self.assertNotIn("token=", opener.opened_url)
        self.assertEqual(f"Bearer {TOKEN}", opener.auth_header)

    def test_read_is_bounded(self) -> None:
        response = _FakeResponse(_real_response_body())
        opener = _FakeOpener(response)
        MODULE.register(TOKEN, SLUG, opener=opener)
        self.assertEqual((4096,), response.read_args)

    def test_plain_hex_body_is_accepted(self) -> None:
        opener = _FakeOpener(_FakeResponse(HEX_ID))
        self.assertEqual(HEX_ID, MODULE.register(TOKEN, SLUG, opener=opener))

    def test_malformed_id_stores_nothing(self) -> None:
        opener = _FakeOpener(_FakeResponse('{"id": "not-hex!!!"}'))
        with self.assertRaises(MODULE.RegistrationError):
            MODULE.register(TOKEN, SLUG, opener=opener)

    def test_http_error_does_not_leak_token(self) -> None:
        opener = _HttpError()
        with self.assertRaises(MODULE.RegistrationError) as caught:
            MODULE.register(TOKEN, SLUG, opener=opener)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn("http", str(caught.exception))

    def test_url_error_does_not_leak_token(self) -> None:
        opener = _UrlError()
        with self.assertRaises(MODULE.RegistrationError) as caught:
            MODULE.register(TOKEN, SLUG, opener=opener)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_exception_text_containing_token_is_not_emitted(self) -> None:
        opener = _TokenLeakingError(TOKEN)
        with self.assertRaises(MODULE.RegistrationError) as caught:
            MODULE.register(TOKEN, SLUG, opener=opener)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual("registration failed (network error)", str(caught.exception))

    def test_sanitized_error_suppresses_cause_from_traceback(self) -> None:
        import traceback

        opener = _TokenLeakingError(TOKEN)
        tb_text = ""
        try:
            MODULE.register(TOKEN, SLUG, opener=opener)
        except MODULE.RegistrationError:
            tb_text = traceback.format_exc()
        self.assertIn("RegistrationError", tb_text)
        self.assertNotIn(TOKEN, tb_text)

    def test_incomplete_read_is_a_fixed_failure(self) -> None:
        opener = _IncompleteReadError()
        with self.assertRaises(MODULE.RegistrationError) as caught:
            MODULE.register(TOKEN, SLUG, opener=opener)
        self.assertEqual("registration failed (network error)", str(caught.exception))

    def test_redirect_is_refused(self) -> None:
        import http.server
        import threading

        seen: list[str] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                seen.append(self.path)
                self.send_response(302)
                self.send_header("Location", "https://evil.example/")
                self.end_headers()

            def log_message(self, *args) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            opener = MODULE._build_opener()
            with self.assertRaises(MODULE.RegistrationError):
                opener.open(f"http://127.0.0.1:{server.server_address[1]}/", timeout=5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(1, len(seen))


class _HttpError:
    def open(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request.get_full_url()
        raise urllib.error.HTTPError(url, 500, "server error", {}, None)


class _UrlError:
    def open(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request.get_full_url()
        raise urllib.error.URLError(url)


class _TokenLeakingError:
    def __init__(self, token: str):
        self._token = token

    def open(self, request, timeout=None):
        raise urllib.error.URLError(f"server rejected {self._token} in the URL")


class _IncompleteReadError:
    def open(self, request, timeout=None):
        import http.client

        raise http.client.IncompleteRead(partial=b"ok", expected=100)


class GitHelperTests(unittest.TestCase):
    def _init_repo(self) -> Path:
        root = Path(tempfile.mkdtemp())
        _git("init", "-q", cwd=root)
        _git("config", "user.email", "test@example.com", cwd=root)
        _git("config", "user.name", "Test", cwd=root)
        (root / "README.md").write_text("hello\n", encoding="utf-8")
        _git("add", "README.md", cwd=root)
        _git("commit", "-q", "-m", "initial", cwd=root)
        return root

    def _remote_checkout(self) -> tuple[Path, Path]:
        """A checkout whose `origin` is a live non-bare repo we can still mutate."""
        origin = self._init_repo()
        (origin / "README.md").write_text("remote readme\n", encoding="utf-8")
        _git("add", "README.md", cwd=origin)
        _git("commit", "-q", "-m", "readme", cwd=origin)
        checkout = Path(tempfile.mkdtemp())
        _git("clone", "-q", str(origin), str(checkout), cwd=origin)
        return checkout, origin

    def test_primary_checkout_root_from_linked_worktree(self) -> None:
        root = self._init_repo()
        lane = root / "lane"
        _git("worktree", "add", "-q", str(lane), "-b", "feat/lane", cwd=root)
        try:
            resolved = MODULE.primary_checkout_root(lane)
            self.assertEqual(root.resolve(), resolved)
        finally:
            _git("worktree", "remove", "--force", str(lane), cwd=root, check=False)

    def test_readme_present_at_commit(self) -> None:
        root = self._init_repo()
        head = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
        self.assertTrue(MODULE.readme_present_at_commit(root, head))
        (root / "README.md").unlink()
        _git("rm", "-q", "README.md", cwd=root)
        _git("commit", "-q", "-m", "remove readme", cwd=root)
        head2 = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
        self.assertFalse(MODULE.readme_present_at_commit(root, head2))

    def test_readme_present_at_invalid_commit_is_none(self) -> None:
        root = self._init_repo()
        self.assertIsNone(MODULE.readme_present_at_commit(root, "deadbeef"))

    def test_primary_checkout_root_bare_repo_is_none(self) -> None:
        root = self._init_repo()
        bare = Path(tempfile.mkdtemp())
        _git("clone", "--bare", "-q", str(root), str(bare), cwd=root)
        self.assertIsNone(MODULE.primary_checkout_root(bare))

    def test_readme_now_returns_fetched_readme(self) -> None:
        checkout, origin = self._remote_checkout()
        (origin / "README.md").write_text("post-clone readme\n", encoding="utf-8")
        _git("add", "README.md", cwd=origin)
        _git("commit", "-q", "-m", "post-clone", cwd=origin)
        self.assertEqual("post-clone readme\n", MODULE.readme_now(checkout, "origin"))

    def test_readme_now_returns_none_when_fetch_fails(self) -> None:
        checkout, origin = self._remote_checkout()
        shutil.rmtree(origin)
        self.assertIsNone(MODULE.readme_now(checkout, "origin"))

    def test_readme_now_reads_live_default_branch_after_change(self) -> None:
        origin = self._init_repo()
        old_default = _git("symbolic-ref", "--short", "HEAD", cwd=origin).stdout.strip()
        checkout = Path(tempfile.mkdtemp())
        _git("clone", "-q", str(origin), str(checkout), cwd=origin)
        # Change the default branch on the origin *after* cloning.
        _git("checkout", "-q", "-b", "renamed", cwd=origin)
        (origin / "README.md").write_text("renamed readme\n", encoding="utf-8")
        _git("add", "README.md", cwd=origin)
        _git("commit", "-q", "-m", "rename", cwd=origin)
        _git("symbolic-ref", "HEAD", "refs/heads/renamed", cwd=origin)
        self.assertEqual("renamed readme\n", MODULE.readme_now(checkout, "origin"))
        # The old default branch is retained locally.
        retained = _git(
            "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{old_default}",
            cwd=checkout, check=False,
        )
        self.assertEqual(0, retained.returncode)

    def test_readme_selection_prefers_exact_names_and_blobs(self) -> None:
        root = self._init_repo()  # already has README.md "hello\n"
        (root / "README.en.md").write_text("english\n", encoding="utf-8")
        (root / "README").write_text("bare\n", encoding="utf-8")
        (root / "README-assets").mkdir()
        (root / "README-assets" / "logo.svg").write_text("<svg/>\n", encoding="utf-8")
        _git("add", "-A", cwd=root)
        _git("commit", "-q", "-m", "extra readmes", cwd=root)
        self.assertEqual("README.md", MODULE.readme_path_at_ref(root, "HEAD"))
        self.assertEqual("hello\n", MODULE.readme_content_at_ref(root, "HEAD"))

    def test_readme_present_requires_supported_blob(self) -> None:
        root = Path(tempfile.mkdtemp())
        _git("init", "-q", cwd=root)
        _git("config", "user.email", "test@example.com", cwd=root)
        _git("config", "user.name", "Test", cwd=root)
        (root / "README.en.md").write_text("english\n", encoding="utf-8")
        (root / "README-assets").mkdir()
        (root / "README-assets" / "x.txt").write_text("x\n", encoding="utf-8")
        _git("add", "-A", cwd=root)
        _git("commit", "-q", "-m", "no supported readme", cwd=root)
        head = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
        self.assertFalse(MODULE.readme_present_at_commit(root, head))

    def test_readme_present_at_commit_matches_case_insensitively(self) -> None:
        root = Path(tempfile.mkdtemp())
        _git("init", "-q", cwd=root)
        _git("config", "user.email", "test@example.com", cwd=root)
        _git("config", "user.name", "Test", cwd=root)
        (root / "readme.md").write_text("lowercase\n", encoding="utf-8")
        _git("add", "readme.md", cwd=root)
        _git("commit", "-q", "-m", "lowercase readme", cwd=root)
        base = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
        self.assertTrue(MODULE.readme_present_at_commit(root, base))
        _git("mv", "readme.md", "README.md", cwd=root)
        _git("commit", "-q", "-m", "rename to canonical", cwd=root)
        self.assertEqual("README.md", MODULE.readme_path_at_ref(root, "HEAD"))
        self.assertTrue(MODULE.readme_present_at_commit(root, base))

    def test_readme_selection_requires_blob_not_symlink(self) -> None:
        root = Path(tempfile.mkdtemp())
        _git("init", "-q", cwd=root)
        _git("config", "user.email", "test@example.com", cwd=root)
        _git("config", "user.name", "Test", cwd=root)
        (root / "target.txt").write_text("target\n", encoding="utf-8")
        os.symlink("target.txt", root / "README.md")
        _git("add", "target.txt", "README.md", cwd=root)
        _git("commit", "-q", "-m", "symlink readme", cwd=root)
        head = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
        self.assertIsNone(MODULE.readme_path_at_ref(root, "HEAD"))
        self.assertFalse(MODULE.readme_present_at_commit(root, head))


class ForkShapeTests(unittest.TestCase):
    def test_decide_fork_shape_is_noop(self) -> None:
        lane = Path(tempfile.mkdtemp())
        doc = json.loads(json.dumps(VALID_DOC))
        doc["github"]["pullRequestRepository"] = "other/upstream"
        (lane / ".dev.json").write_text(json.dumps(doc), encoding="utf-8")
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = MODULE.main(["decide", "--repo-dir", str(lane), "--visibility", "public"])
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("noop", out["action"])
        self.assertEqual("fork_shape", out["reason"])

    def test_apply_fork_shape_is_noop(self) -> None:
        lane = Path(tempfile.mkdtemp())
        doc = json.loads(json.dumps(VALID_DOC))
        doc["github"]["pullRequestRepository"] = "other/upstream"
        (lane / ".dev.json").write_text(json.dumps(doc), encoding="utf-8")
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "decline"])
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("fork_shape", out["reason"])


class ApplyIntegrationTests(unittest.TestCase):
    def _setup(self) -> tuple[Path, Path]:
        root = Path(tempfile.mkdtemp())
        _git("init", "-q", cwd=root)
        _git("config", "user.email", "test@example.com", cwd=root)
        _git("config", "user.name", "Test", cwd=root)
        (root / "README.md").write_text("hello\n", encoding="utf-8")
        _git("add", "README.md", cwd=root)
        _git("commit", "-q", "-m", "initial", cwd=root)
        _git("remote", "add", "origin", ORIGIN_URL, cwd=root)
        lane = root / "lane"
        _git("worktree", "add", "-q", str(lane), "-b", "feat/lane", cwd=root)
        (lane / ".dev.json").write_text(json.dumps(VALID_DOC), encoding="utf-8")
        return root, lane

    def _setup_with_tracked_primary_showcase(self) -> tuple[Path, Path]:
        root, lane = self._setup()
        (root / ".dev.json").write_text(
            json.dumps({**VALID_DOC, "showcase": {"registerApproved": True, "decidedAt": "2026-11-01"}}),
            encoding="utf-8",
        )
        _git("add", ".dev.json", cwd=root)
        _git("commit", "-q", "-m", "tracked config", cwd=root)
        return root, lane

    def test_apply_register_writes_primary_and_preserves_github(self) -> None:
        root, lane = self._setup()
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        try:
            with mock.patch.object(MODULE, "register", return_value="abcdef1234567890"):
                code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "register"])
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env

        self.assertEqual(0, code)
        primary_cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertEqual(VALID_DOC["github"], primary_cfg["github"])
        self.assertEqual("abcdef1234567890", primary_cfg["showcase"]["privateId"])
        self.assertTrue(primary_cfg["showcase"]["registerApproved"])
        self.assertNotIn(TOKEN, (root / ".dev.json").read_text(encoding="utf-8"))

    def test_apply_register_failure_records_consent_only(self) -> None:
        root, lane = self._setup()
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        try:
            with mock.patch.object(
                MODULE, "register", side_effect=MODULE.RegistrationError("registration failed (network error)")
            ):
                code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "register"])
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env

        self.assertEqual(0, code)
        primary_cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertTrue(primary_cfg["showcase"]["registerApproved"])
        self.assertNotIn("privateId", primary_cfg["showcase"])
        self.assertNotIn("registered", primary_cfg["showcase"])
        self.assertNotIn(TOKEN, (root / ".dev.json").read_text(encoding="utf-8"))

    def test_apply_decline_records_false(self) -> None:
        root, lane = self._setup()
        code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "decline"])
        self.assertEqual(0, code)
        primary_cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertFalse(primary_cfg["showcase"]["badge"])

    def test_apply_decline_clears_register_approved(self) -> None:
        root, lane = self._setup()
        (root / ".dev.json").write_text(
            json.dumps({**VALID_DOC, "showcase": {"registerApproved": True, "showBadge": True, "decidedAt": "2026-11-01"}}),
            encoding="utf-8",
        )
        code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "decline"])
        self.assertEqual(0, code)
        primary_cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertFalse(primary_cfg["showcase"]["badge"])
        self.assertFalse(primary_cfg["showcase"]["registerApproved"])
        self.assertFalse(primary_cfg["showcase"]["showBadge"])

    def test_apply_approve_then_landed_clears_badge_approved(self) -> None:
        root, lane = self._setup()
        code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "approve"])
        self.assertEqual(0, code)
        cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["showcase"]["badgeApproved"])

        code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "landed"])
        self.assertEqual(0, code)
        cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["showcase"]["badge"])
        self.assertFalse(cfg["showcase"]["badgeApproved"])

    def test_apply_decline_clears_badge_approved(self) -> None:
        root, lane = self._setup()
        (root / ".dev.json").write_text(
            json.dumps({**VALID_DOC, "showcase": {"badgeApproved": True, "decidedAt": "2026-11-01"}}),
            encoding="utf-8",
        )
        code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "decline"])
        self.assertEqual(0, code)
        cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["showcase"]["badge"])
        self.assertFalse(cfg["showcase"]["badgeApproved"])

    def test_apply_register_visible_returns_block_and_no_second_registration(self) -> None:
        root, lane = self._setup()
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        try:
            with mock.patch.object(MODULE, "register", return_value="abcdef1234567890"):
                code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "register", "--visible"])

            self.assertEqual(0, code)
            cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
            self.assertEqual("abcdef1234567890", cfg["showcase"]["privateId"])
            self.assertTrue(cfg["showcase"]["showBadge"])

            # A second run must not re-register; it returns the block with no call.
            with mock.patch.object(MODULE, "register") as fake_register2:
                buf = io.StringIO()
                with mock.patch("sys.stdout", buf):
                    MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "register", "--visible"])
                fake_register2.assert_not_called()
            out = json.loads(buf.getvalue())
            self.assertTrue(out.get("already"))
            self.assertIn("?p=abcdef1234567890", out["block"])
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env

    def test_apply_landed_clears_show_badge(self) -> None:
        root, lane = self._setup()
        (root / ".dev.json").write_text(
            json.dumps({
                **VALID_DOC,
                "showcase": {
                    "registered": True, "privateId": "abcdef1234567890",
                    "showBadge": True, "decidedAt": "2026-11-01",
                },
            }),
            encoding="utf-8",
        )
        code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "landed"])
        self.assertEqual(0, code)
        cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["showcase"]["badge"])
        self.assertFalse(cfg["showcase"]["showBadge"])

    def test_apply_register_does_not_recall_when_private_id_present(self) -> None:
        root, lane = self._setup()
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        (root / ".dev.json").write_text(
            json.dumps({**VALID_DOC, "showcase": {"privateId": "abcdef1234567890", "registerApproved": True, "registered": True}}),
            encoding="utf-8",
        )
        try:
            with mock.patch.object(MODULE, "register") as fake_register:
                code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "register"])
                fake_register.assert_not_called()
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env
        self.assertEqual(0, code)

    def test_lane_config_is_never_written(self) -> None:
        root, lane = self._setup()
        before = (lane / ".dev.json").read_text(encoding="utf-8")
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        try:
            with mock.patch.object(MODULE, "register", return_value="abcdef1234567890"):
                MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "register"])
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env
        self.assertEqual(before, (lane / ".dev.json").read_text(encoding="utf-8"))

    def test_tracked_primary_config_is_noop_not_retry_register(self) -> None:
        root, lane = self._setup_with_tracked_primary_showcase()
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        try:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                code = MODULE.main(["decide", "--repo-dir", str(lane), "--visibility", "private"])
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("noop", out["action"])
        self.assertEqual("fail_closed", out["reason"])

    def test_tracked_primary_config_blocks_apply_register(self) -> None:
        root, lane = self._setup_with_tracked_primary_showcase()
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        try:
            with mock.patch.object(MODULE, "register") as fake_register:
                code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "register"])
                fake_register.assert_not_called()
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env
        self.assertEqual(0, code)
        primary_cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertTrue(primary_cfg["showcase"]["registerApproved"])
        self.assertNotIn("privateId", primary_cfg["showcase"])

    def test_fetch_identity_mismatch_is_noop(self) -> None:
        root, lane = self._setup()
        _git("remote", "set-url", "origin", "https://github.com/other/upstream.git", cwd=root)
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = MODULE.main(["decide", "--repo-dir", str(lane), "--visibility", "public"])
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("noop", out["action"])
        self.assertEqual("fail_closed", out["reason"])

    def test_existing_unignored_primary_config_is_excluded_and_accepted(self) -> None:
        root, lane = self._setup()
        (root / ".dev.json").write_text(json.dumps(VALID_DOC), encoding="utf-8")
        code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "decline"])
        self.assertEqual(0, code)
        cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["showcase"]["badge"])
        self.assertTrue(dev_config.is_ignored(root, ".dev.json"))

    def test_ensure_excluded_failure_blocks_register(self) -> None:
        root, lane = self._setup()
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        try:
            with mock.patch.object(dev_config, "ensure_excluded", return_value=False):
                with mock.patch.object(MODULE, "register") as fake_register:
                    code = MODULE.main(["apply", "--repo-dir", str(lane), "--consent", "register"])
                    fake_register.assert_not_called()
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env
        self.assertEqual(2, code)
        self.assertFalse((root / ".dev.json").exists())

    def test_apply_register_public_visibility_is_noop(self) -> None:
        root, lane = self._setup()
        old_env = os.environ.get(MODULE.TOKEN_ENV)
        os.environ[MODULE.TOKEN_ENV] = TOKEN
        try:
            with mock.patch.object(MODULE, "register") as fake_register:
                buf = io.StringIO()
                with mock.patch("sys.stdout", buf):
                    code = MODULE.main(
                        ["apply", "--repo-dir", str(lane), "--consent", "register", "--visibility", "public"]
                    )
                fake_register.assert_not_called()
        finally:
            if old_env is None:
                os.environ.pop(MODULE.TOKEN_ENV, None)
            else:
                os.environ[MODULE.TOKEN_ENV] = old_env
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("noop", out["status"])
        self.assertEqual("unsupported_visibility", out["reason"])
        self.assertFalse((root / ".dev.json").exists())

    def test_landed_detection_records_badge_true_then_hand_removal(self) -> None:
        root, lane = self._setup()
        # First run: badge present on the default branch -> record badge: true.
        with mock.patch.object(MODULE, "fetch_identity_matches", return_value=True), \
             mock.patch.object(
                 MODULE, "readme_now",
                 return_value="built with https://svg.khaentertainment.com/badge.svg",
             ):
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                code = MODULE.main(["decide", "--repo-dir", str(lane), "--visibility", "public"])
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("noop", out["action"])
        self.assertEqual("landed", out["reason"])
        cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["showcase"]["badge"])

        # Second run: badge deleted (no marker) -> hand_removal.
        with mock.patch.object(MODULE, "fetch_identity_matches", return_value=True), \
             mock.patch.object(MODULE, "readme_now", return_value="no badge here"):
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                code = MODULE.main(["decide", "--repo-dir", str(lane), "--visibility", "public"])
        out = json.loads(buf.getvalue())
        self.assertEqual("hand_removal", out["action"])

    def test_landed_detection_skips_recorded_decline(self) -> None:
        root, lane = self._setup()
        (root / ".dev.json").write_text(
            json.dumps({**VALID_DOC, "showcase": {"badge": False, "decidedAt": "2026-11-01"}}),
            encoding="utf-8",
        )
        with mock.patch.object(MODULE, "fetch_identity_matches", return_value=True), \
             mock.patch.object(
                 MODULE, "readme_now",
                 return_value="built with https://svg.khaentertainment.com/badge.svg",
             ):
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                code = MODULE.main(["decide", "--repo-dir", str(lane), "--visibility", "public"])
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("noop", out["action"])
        self.assertEqual("declined", out["reason"])
        cfg = json.loads((root / ".dev.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["showcase"]["badge"])

    def test_landed_detection_skips_missing_readme_skill(self) -> None:
        root, lane = self._setup()
        with mock.patch.object(MODULE, "fetch_identity_matches", return_value=True), \
             mock.patch.object(
                 MODULE, "readme_now",
                 return_value="built with https://svg.khaentertainment.com/badge.svg",
             ), \
             mock.patch.object(MODULE, "readme_skill_present", return_value=False):
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                code = MODULE.main(["decide", "--repo-dir", str(lane), "--visibility", "public"])
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("noop", out["action"])
        self.assertEqual("readme_skill_missing", out["reason"])
        self.assertFalse((root / ".dev.json").exists())


class AtomicCreateTests(unittest.TestCase):
    def test_failed_atomic_create_leaves_no_partial_file(self) -> None:
        root = Path(tempfile.mkdtemp())
        path = root / ".dev.json"

        def failing_link(src: str, dst: str, *args, **kwargs) -> None:
            raise OSError("boom")

        with mock.patch.object(dev_config.os, "link", side_effect=failing_link):
            with self.assertRaises(OSError):
                dev_config.create_config_atomic(path, VALID_DOC)

        self.assertFalse(path.exists())
        self.assertEqual([], list(root.iterdir()))

    def test_write_showcase_uses_create_config_atomic_not_create_config(self) -> None:
        root = Path(tempfile.mkdtemp())
        with mock.patch.object(dev_config, "ensure_excluded", return_value=True), \
             mock.patch.object(dev_config, "create_config_atomic") as atomic, \
             mock.patch.object(dev_config, "create_config") as plain:
            MODULE.write_showcase(root, VALID_DOC, {"badge": False, "decidedAt": "2026-11-01"})
        atomic.assert_called_once()
        plain.assert_not_called()


class ShowcaseConfigSchemaTests(unittest.TestCase):
    def _with_showcase(self, block):
        doc = json.loads(json.dumps(VALID_DOC))
        doc["showcase"] = block
        return doc

    def test_valid_showcase_round_trips(self) -> None:
        block = {"badge": False, "registered": True, "privateId": "9f2c1a3b4c5d6e7f", "decidedAt": "2026-11-01"}
        doc = self._with_showcase(block)
        parsed = dev_config.parse_config(json.dumps(doc))
        self.assertEqual(block, parsed["showcase"])

    def test_badge_approved_field_round_trips(self) -> None:
        doc = self._with_showcase({"badgeApproved": True, "decidedAt": "2026-11-01"})
        parsed = dev_config.parse_config(json.dumps(doc))
        self.assertTrue(parsed["showcase"]["badgeApproved"])

    def test_badge_approved_must_be_boolean(self) -> None:
        doc = self._with_showcase({"badgeApproved": "yes"})
        with self.assertRaises(dev_config.ConfigError):
            dev_config.parse_config(json.dumps(doc))

    def test_missing_showcase_still_validates(self) -> None:
        parsed = dev_config.parse_config(json.dumps(VALID_DOC))
        self.assertNotIn("showcase", parsed)

    def test_unknown_showcase_field_is_rejected(self) -> None:
        doc = self._with_showcase({"badge": True, "unknownField": 1})
        with self.assertRaises(dev_config.ConfigError) as caught:
            dev_config.parse_config(json.dumps(doc))
        self.assertEqual("unknown_field", caught.exception.code)

    def test_secret_shaped_showcase_field_is_rejected(self) -> None:
        doc = self._with_showcase({"badge": True, "token": "x"})
        with self.assertRaises(dev_config.ConfigError) as caught:
            dev_config.parse_config(json.dumps(doc))
        self.assertEqual("secret_field_rejected", caught.exception.code)

    def test_private_id_must_be_hex(self) -> None:
        doc = self._with_showcase({"privateId": "not-hex"})
        with self.assertRaises(dev_config.ConfigError) as caught:
            dev_config.parse_config(json.dumps(doc))
        self.assertEqual("invalid_field", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
