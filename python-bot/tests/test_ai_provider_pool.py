# Credits: gogeta_gg
import os
import unittest

from cogs.ai_provider_pool import ProviderKeyPool


class ProviderKeyPoolTests(unittest.TestCase):
    def setUp(self):
        self.names = ["CHAOS_TEST_PROVIDER_KEY", "CHAOS_TEST_PROVIDER_KEY_1", "CHAOS_TEST_PROVIDER_KEY_2"]
        self.old = {name: os.environ.get(name) for name in self.names}
        os.environ[self.names[0]] = "key-a"
        os.environ[self.names[1]] = "key-b"
        os.environ[self.names[2]] = "key-a"  # duplicates must be ignored
        self.pool = ProviderKeyPool(self.names[0], cooldown=5, failure_threshold=1)

    def tearDown(self):
        for name, value in self.old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_numbered_keys_and_duplicates(self):
        values = self.pool.keys()
        self.assertEqual([name for name, _ in values], [self.names[0], self.names[1]])
        self.assertEqual(self.pool.configured_count(), 2)

    def test_auth_failure_quarantines_one_key_not_the_pool(self):
        values = self.pool.available()
        bad_name = values[0][0]
        self.pool.failure(bad_name, "auth")
        remaining = self.pool.available()
        self.assertEqual(len(remaining), 1)
        self.assertNotEqual(remaining[0][0], bad_name)
        self.pool.success(remaining[0][0])
        self.assertEqual(len(self.pool.available()), 1)


if __name__ == "__main__":
    unittest.main()
