"""
Unit tests for OAuth account resolution helpers.

These tests do not require live Google/GitHub credentials.
LIVE OAUTH TEST: NOT RUN — credentials/provider environment unavailable.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is importable when tests are run from repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestNormalizeAndSafeRedirect(unittest.TestCase):
    def test_normalize_email(self):
        from app.auth.oauth_service import normalize_email
        self.assertEqual(normalize_email('User@Example.COM'), 'user@example.com')
        self.assertEqual(normalize_email('  a@b.co  '), 'a@b.co')
        self.assertEqual(normalize_email(None), '')
        self.assertEqual(normalize_email(''), '')

    def test_safe_next_redirect_blocks_open_redirect(self):
        from flask import Flask
        app = Flask(__name__)
        app.config['SERVER_NAME'] = 'example.test'
        app.add_url_rule('/', endpoint='main.index', view_func=lambda: 'ok')

        with app.app_context():
            from app.auth.oauth_service import safe_next_redirect
            self.assertEqual(safe_next_redirect(None), 'http://example.test/')
            self.assertEqual(safe_next_redirect('/dashboard'), '/dashboard')
            self.assertEqual(safe_next_redirect('https://evil.test/phish'), 'http://example.test/')
            self.assertEqual(safe_next_redirect('//evil.test'), 'http://example.test/')
            self.assertEqual(safe_next_redirect('javascript:alert(1)'), 'http://example.test/')


class TestOAuthIdentityValidation(unittest.TestCase):
    """Mocked DB / User resolution paths."""

    def _identity(self, **kwargs):
        from app.auth.oauth_service import OAuthIdentity
        base = dict(
            provider='google',
            provider_user_id='sub-123',
            email='user@example.com',
            email_verified=True,
            name='Test User',
            username_hint='user',
            avatar_url='https://example.com/a.png',
        )
        base.update(kwargs)
        return OAuthIdentity(**base)

    @patch('app.auth.oauth_service.is_temp_email', return_value=False)
    @patch('app.auth.oauth_service._find_by_email', return_value=None)
    @patch('app.auth.oauth_service._find_by_oauth', return_value=None)
    def test_reject_unverified_email(self, *_mocks):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            from app.auth.oauth_service import resolve_oauth_user
            result = resolve_oauth_user(self._identity(email_verified=False))
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, 'unverified_email')

    @patch('app.auth.oauth_service.is_temp_email', return_value=False)
    def test_reject_missing_email(self, *_mocks):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            from app.auth.oauth_service import resolve_oauth_user
            result = resolve_oauth_user(self._identity(email=''))
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, 'missing_email')

    @patch('app.auth.oauth_service.is_temp_email', return_value=True)
    def test_reject_temp_email(self, *_mocks):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            from app.auth.oauth_service import resolve_oauth_user
            result = resolve_oauth_user(self._identity(email='x@tempmail.com'))
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, 'temp_email')

    @patch('app.auth.oauth_service.is_temp_email', return_value=False)
    def test_reject_missing_provider_id(self, *_mocks):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            from app.auth.oauth_service import resolve_oauth_user
            result = resolve_oauth_user(self._identity(provider_user_id=''))
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, 'missing_provider_id')


if __name__ == '__main__':
    unittest.main()
