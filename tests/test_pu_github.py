"""Tests for pu_github.py."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import truststore  # noqa: E402  pylint: disable=wrong-import-position

import pu_github  # noqa: E402  pylint: disable=wrong-import-position


class TestSSLContext(unittest.TestCase):
    def test_uses_os_verifier(self):
        # The stdlib default context breaks on fresh Windows installs whose
        # root store isn't populated yet -- see pu_github's docstring.
        self.assertIsInstance(pu_github._SSL_CONTEXT, truststore.SSLContext)  # pylint: disable=protected-access


if __name__ == "__main__":
    unittest.main()
