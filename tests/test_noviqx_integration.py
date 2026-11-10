"""Unit tests for the optional NoviqX integration."""
import base64
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

try:
    import jwt
    from integrations.noviqx.auth import (
        GitHubAppAuth, NoviqXConfigurationError, NoviqXAuthenticationError
    )
    from integrations.noviqx.github_api import NoviqXGitHub
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
except ImportError:
    jwt = None


class _Response:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode()
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


@unittest.skipIf(jwt is None, "Install requirements-noviqx.txt for NoviqX tests")
class TestNoviqXAuth(unittest.TestCase):
    def setUp(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        self.temp = tempfile.TemporaryDirectory()
        self.key_path = Path(self.temp.name) / "test-key.pem"
        self.key_path.write_text(pem, encoding="utf-8")
        self.now = 1_800_000_000

    def tearDown(self):
        self.temp.cleanup()

    def test_app_jwt_has_expected_claims_and_short_lifetime(self):
        auth = GitHubAppAuth("5667949", "179860235", self.key_path,
                             clock=lambda: self.now)
        token = auth.create_app_jwt()
        claims = jwt.decode(token, options={"verify_signature": False})
        self.assertEqual(claims["iss"], "5667949")
        self.assertEqual(claims["iat"], self.now - 30)
        self.assertEqual(claims["exp"], self.now + 480)

    def test_missing_configuration_fails_clearly(self):
        with patch.dict(os.environ, {}, clear=True):
            auth = GitHubAppAuth()
        with self.assertRaises(NoviqXConfigurationError):
            auth.create_app_jwt()

    def test_installation_token_is_cached_until_near_expiry(self):
        expiry = datetime.fromtimestamp(
            self.now + 3600, tz=timezone.utc
        ).isoformat().replace("+00:00", "Z")
        calls = []

        def opener(request, timeout):
            calls.append(request)
            return _Response({"token": "test-installation-token", "expires_at": expiry})

        auth = GitHubAppAuth("5667949", "179860235", self.key_path,
                             opener=opener, clock=lambda: self.now)
        self.assertEqual(auth.get_installation_token(), "test-installation-token")
        self.assertEqual(auth.get_installation_token(), "test-installation-token")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "POST")
        self.assertIn("/app/installations/179860235/access_tokens", calls[0].full_url)

    def test_invalid_repository_is_rejected_before_request(self):
        class NoAuth:
            api_root = "https://api.github.com"
        client = NoviqXGitHub(auth=NoAuth())
        with self.assertRaises(ValueError):
            client.get_repository("../bad")


    def test_get_file_decodes_contents_and_returns_blob_sha(self):
        payload = {
            "type": "file",
            "path": "version.txt",
            "encoding": "base64",
            "content": base64.b64encode(b"2.1\n").decode("ascii"),
            "sha": "blob-sha",
            "html_url": "https://github.com/owner/repo/blob/main/version.txt",
        }
        calls = []

        class FakeAuth:
            api_root = "https://api.github.com"

            def get_installation_token(self):
                return "test-token"

        def opener(request, timeout):
            calls.append(request)
            return _Response(payload)

        client = NoviqXGitHub(auth=FakeAuth(), opener=opener)
        result = client.get_file("owner/repo", "version.txt", "main")

        self.assertEqual(result["content"], "2.1\n")
        self.assertEqual(result["sha"], "blob-sha")
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["size_bytes"], len("2.1\n".encode("utf-8")))
        self.assertIn("ref=main", calls[0].full_url)

    def test_get_file_reports_utf8_byte_length_not_character_count(self):
        content = "Nova — هوش مصنوعی 🚀"
        payload = {
            "type": "file",
            "path": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "sha": "unicode-blob-sha",
        }

        class FakeAuth:
            api_root = "https://api.github.com"

            def get_installation_token(self):
                return "test-token"

        client = NoviqXGitHub(
            auth=FakeAuth(),
            opener=lambda request, timeout: _Response(payload, status=200),
        )
        result = client.get_file("owner/repo", "README.md", "main")

        self.assertEqual(result["content"], content)
        self.assertEqual(result["size_bytes"], len(content.encode("utf-8")))
        self.assertNotEqual(result["size_bytes"], len(content))
        self.assertEqual(result["http_status"], 200)

    def test_get_file_rejects_github_responses_without_inline_content(self):
        from integrations.noviqx.github_api import GitHubAPIError

        class FakeAuth:
            api_root = "https://api.github.com"

            def get_installation_token(self):
                return "test-token"

        payload = {
            "type": "file",
            "path": "large.bin",
            "encoding": "none",
            "content": "",
            "sha": "blob-sha",
            "size": 2_000_000,
        }
        client = NoviqXGitHub(
            auth=FakeAuth(),
            opener=lambda request, timeout: _Response(payload),
        )
        with self.assertRaises(GitHubAPIError):
            client.get_file("owner/repo", "large.bin", "main")

    def test_update_file_rejects_stale_blob_sha_before_put(self):
        calls = []

        class FakeAuth:
            api_root = "https://api.github.com"

            def get_installation_token(self):
                return "test-token"

        def opener(request, timeout):
            calls.append(request)
            return _Response({
                "type": "file",
                "path": "version.txt",
                "encoding": "base64",
                "content": base64.b64encode(b"2.1\n").decode("ascii"),
                "sha": "current-blob-sha",
            })

        client = NoviqXGitHub(auth=FakeAuth(), opener=opener)
        from integrations.noviqx.github_api import GitHubAPIError

        with self.assertRaises(GitHubAPIError):
            client.put_file(
                "owner/repo", "version.txt", "2.2\n",
                "Bump version to 2.2", "main",
                expected_sha="stale-blob-sha",
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "GET")

    def test_update_file_sends_matching_blob_sha_to_contents_api(self):
        calls = []

        class FakeAuth:
            api_root = "https://api.github.com"

            def get_installation_token(self):
                return "test-token"

        def opener(request, timeout):
            calls.append(request)
            if request.method == "GET":
                return _Response({
                    "type": "file",
                    "path": "version.txt",
                    "encoding": "base64",
                    "content": base64.b64encode(b"2.1\n").decode("ascii"),
                    "sha": "current-blob-sha",
                })
            return _Response({
                "commit": {"sha": "new-commit-sha"},
                "content": {"sha": "new-blob-sha", "html_url": "https://github.com/owner/repo/blob/main/version.txt"},
            })

        client = NoviqXGitHub(auth=FakeAuth(), opener=opener)
        result = client.put_file(
            "owner/repo", "version.txt", "2.2\n",
            "Bump version to 2.2", "main",
            expected_sha="current-blob-sha",
        )

        self.assertEqual(result["commit"]["sha"], "new-commit-sha")
        self.assertEqual(calls[-1].method, "PUT")
        request_payload = json.loads(calls[-1].data.decode("utf-8"))
        self.assertEqual(request_payload["sha"], "current-blob-sha")


    def test_api_error_preserves_http_status_for_callers(self):
        from integrations.noviqx.github_api import GitHubAPIError

        class FakeAuth:
            api_root = "https://api.github.com"

            def get_installation_token(self):
                return "test-token"

        def forbidden(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 403, "Forbidden", None, None
            )

        client = NoviqXGitHub(auth=FakeAuth(), opener=forbidden)
        with self.assertRaises(GitHubAPIError) as caught:
            client.get_file("owner/repo", "version.txt", "main")
        self.assertEqual(caught.exception.status_code, 403)

    def test_update_does_not_treat_permission_error_as_missing_file(self):
        from integrations.noviqx.github_api import GitHubAPIError

        class FakeAuth:
            api_root = "https://api.github.com"

            def get_installation_token(self):
                return "test-token"

        calls = []

        def forbidden(request, timeout):
            calls.append(request)
            raise __import__("urllib.error").error.HTTPError(
                request.full_url, 403, "Forbidden", None, None
            )

        client = NoviqXGitHub(auth=FakeAuth(), opener=forbidden)
        with self.assertRaises(GitHubAPIError) as caught:
            client.put_file(
                "owner/repo", "version.txt", "2.2\\n",
                "Update version", "main", expected_sha="old-blob-sha",
            )
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual([call.method for call in calls], ["GET"])

    def test_safe_branch_rejects_invalid_git_refs(self):
        for branch in ("feature//broken", "bad branch", "trailing.", "name.lock", "a@{b}"):
            with self.subTest(branch=branch):
                with self.assertRaises(ValueError):
                    NoviqXGitHub._safe_branch(branch)

    def test_request_refreshes_installation_token_once_after_401(self):
        class FakeAuth:
            api_root = "https://api.github.com"

            def __init__(self):
                self.token = "expired-token"
                self.refreshes = 0

            def get_installation_token(self):
                return self.token

            def invalidate_token(self, token=None):
                self.asserted_token = token
                self.token = "fresh-token"
                self.refreshes += 1

        auth = FakeAuth()
        calls = []

        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 401, "Unauthorized", None, None
                )
            return _Response({"full_name": "owner/repo"})

        client = NoviqXGitHub(auth=auth, opener=opener)
        result = client.get_repository("owner/repo")

        self.assertEqual(result["full_name"], "owner/repo")
        self.assertEqual(auth.refreshes, 1)
        self.assertEqual(auth.asserted_token, "expired-token")
        self.assertEqual(len(calls), 2)
        self.assertIn("Bearer expired-token", calls[0].headers["Authorization"])
        self.assertIn("Bearer fresh-token", calls[1].headers["Authorization"])



if __name__ == "__main__":
    unittest.main()
