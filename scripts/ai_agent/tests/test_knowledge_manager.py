# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for Knowledge Manager and Token Counter.
==============================================

Run with: python -m pytest deskagent/scripts/ai_agent/tests/test_knowledge_manager.py -v
Or standalone: python deskagent/scripts/ai_agent/tests/test_knowledge_manager.py
"""

import sys
import tempfile
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest


class TestTokenCounter(unittest.TestCase):
    """Tests for TokenCounter class."""

    def setUp(self):
        from token_counter import TokenCounter
        self.counter = TokenCounter()

    def test_count_empty_string(self):
        """Empty string should return 0 tokens."""
        self.assertEqual(self.counter.count(""), 0)

    def test_count_simple_text(self):
        """Simple text should return reasonable token count."""
        text = "Hello, world!"
        tokens = self.counter.count(text)
        # Should be around 3-5 tokens
        self.assertGreater(tokens, 0)
        self.assertLess(tokens, 10)

    def test_count_german_text(self):
        """German text should also work."""
        text = "DeskAgent ist ein KI-gestützter Desktop-Assistent."
        tokens = self.counter.count(text)
        self.assertGreater(tokens, 5)

    def test_count_long_text(self):
        """Long text should return proportionally more tokens."""
        short_text = "Hello"
        long_text = "Hello " * 100
        short_tokens = self.counter.count(short_text)
        long_tokens = self.counter.count(long_text)
        # Long text should have significantly more tokens
        self.assertGreater(long_tokens, short_tokens * 50)

    def test_count_file(self):
        """Counting tokens in a file should work."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write("# Test Knowledge\n\nThis is test content with some words.")
            temp_path = f.name

        try:
            tokens = self.counter.count_file(temp_path)
            self.assertGreater(tokens, 5)
        finally:
            Path(temp_path).unlink()

    def test_count_file_nonexistent(self):
        """Non-existent file should return 0."""
        tokens = self.counter.count_file("/nonexistent/path.md")
        self.assertEqual(tokens, 0)

    def test_cache_stats(self):
        """Cache stats should be accessible."""
        stats = self.counter.get_cache_stats()
        self.assertIn("cached_files", stats)
        self.assertIn("using_tiktoken", stats)
        self.assertIn("encoding", stats)


class TestKnowledgeManager(unittest.TestCase):
    """Tests for KnowledgeManager class."""

    def setUp(self):
        """Create a temporary knowledge directory with test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.knowledge_dir = Path(self.temp_dir) / "knowledge"
        self.knowledge_dir.mkdir()

        # Create test knowledge files
        (self.knowledge_dir / "product.md").write_text(
            "# Product Info\n\nDeskAgent is an AI assistant.\n" * 10,
            encoding='utf-8'
        )
        (self.knowledge_dir / "pricing.md").write_text(
            "# Pricing\n\n- Starter: $29/month\n- Pro: $99/month\n" * 10,
            encoding='utf-8'
        )
        (self.knowledge_dir / "faq.md").write_text(
            "# FAQ\n\nQ: What is DeskAgent?\nA: An AI assistant.\n" * 10,
            encoding='utf-8'
        )

        from knowledge_manager import KnowledgeManager
        self.km = KnowledgeManager(knowledge_dir=self.knowledge_dir)

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_load_all_knowledge(self):
        """Loading without pattern should load all files."""
        content, stats = self.km.load_for_agent(pattern=None)

        self.assertGreater(len(content), 0)
        self.assertEqual(stats.files_count, 3)
        self.assertIn("product", content.lower())
        self.assertIn("pricing", content.lower())
        self.assertIn("faq", content.lower())

    def test_load_with_pattern(self):
        """Loading with pattern should filter files."""
        content, stats = self.km.load_for_agent(pattern="product")

        self.assertEqual(stats.files_count, 1)
        self.assertIn("product", content.lower())
        self.assertNotIn("faq", content.lower())

    def test_load_with_regex_pattern(self):
        """Loading with regex pattern should work."""
        content, stats = self.km.load_for_agent(pattern="product|pricing")

        self.assertEqual(stats.files_count, 2)
        self.assertIn("product", content.lower())
        self.assertIn("pricing", content.lower())
        self.assertNotIn("faq", content.lower())

    def test_load_empty_pattern(self):
        """Empty pattern should load nothing."""
        content, stats = self.km.load_for_agent(pattern="")

        self.assertEqual(content, "")
        self.assertEqual(stats.files_count, 0)
        self.assertEqual(stats.mode, "disabled")

    def test_stats_tokens(self):
        """Stats should include token counts."""
        content, stats = self.km.load_for_agent(pattern=None)

        self.assertGreater(stats.total_tokens, 0)
        self.assertGreater(stats.total_chars, 0)
        self.assertEqual(len(stats.files), 3)

        # Each file should have tokens counted
        for file_info in stats.files:
            self.assertIn("tokens", file_info)
            self.assertGreater(file_info["tokens"], 0)

    def test_stats_threshold(self):
        """Stats should indicate threshold status."""
        content, stats = self.km.load_for_agent(pattern=None)

        self.assertEqual(stats.threshold_tokens, 30000)
        # Our small test files should not exceed threshold
        self.assertFalse(stats.exceeds_threshold)
        self.assertEqual(stats.mode, "full")

    def test_caching(self):
        """Second load should be cached."""
        # First load
        content1, stats1 = self.km.load_for_agent(pattern=None)
        self.assertFalse(stats1.cache_hit)

        # Second load - should be cached
        content2, stats2 = self.km.load_for_agent(pattern=None)
        self.assertTrue(stats2.cache_hit)
        self.assertEqual(content1, content2)

    def test_force_reload(self):
        """Force reload should bypass cache."""
        # First load
        content1, stats1 = self.km.load_for_agent(pattern=None)

        # Force reload
        content2, stats2 = self.km.load_for_agent(pattern=None, force_reload=True)
        self.assertFalse(stats2.cache_hit)

    def test_invalidate_cache(self):
        """Cache invalidation should work."""
        # Load and cache
        self.km.load_for_agent(pattern=None)

        # Invalidate
        self.km.invalidate_cache()

        # Next load should not be cached
        content, stats = self.km.load_for_agent(pattern=None)
        self.assertFalse(stats.cache_hit)

    def test_stats_to_dict(self):
        """Stats should be serializable to dict."""
        content, stats = self.km.load_for_agent(pattern=None)

        stats_dict = stats.to_dict()
        self.assertIsInstance(stats_dict, dict)
        self.assertIn("files_count", stats_dict)
        self.assertIn("total_tokens", stats_dict)
        self.assertIn("exceeds_threshold", stats_dict)

    def test_stats_summary(self):
        """Stats summary should be a string."""
        content, stats = self.km.load_for_agent(pattern=None)

        summary = stats.summary()
        self.assertIsInstance(summary, str)
        self.assertIn("files", summary.lower())
        self.assertIn("tokens", summary.lower())

    def test_stats_log_line(self):
        """Stats log line should be suitable for logging."""
        content, stats = self.km.load_for_agent(pattern=None)

        log_line = stats.log_line()
        self.assertIsInstance(log_line, str)
        self.assertIn("Knowledge:", log_line)

    def test_get_stats(self):
        """Manager stats should be accessible."""
        self.km.load_for_agent(pattern=None)

        stats = self.km.get_stats()
        self.assertIn("settings", stats)
        self.assertIn("cache", stats)
        self.assertIn("last_load", stats)

    def test_measure_pattern(self):
        """Measuring without caching should work."""
        stats1 = self.km.measure_pattern(pattern=None)
        stats2 = self.km.measure_pattern(pattern=None)

        # Both should have same file count but neither cached
        self.assertEqual(stats1.files_count, stats2.files_count)


class TestKnowledgeManagerThreshold(unittest.TestCase):
    """Tests for threshold detection."""

    def setUp(self):
        """Create knowledge that exceeds threshold."""
        self.temp_dir = tempfile.mkdtemp()
        self.knowledge_dir = Path(self.temp_dir) / "knowledge"
        self.knowledge_dir.mkdir()

        # Create a large file (~40k tokens = ~140k chars)
        large_content = "This is test content. " * 7000  # ~140k chars ≈ 40k tokens
        (self.knowledge_dir / "large.md").write_text(large_content, encoding='utf-8')

        from knowledge_manager import KnowledgeManager
        # Low threshold for testing
        self.km = KnowledgeManager(
            knowledge_dir=self.knowledge_dir,
            config={"knowledge": {"threshold_tokens": 1000}}  # Very low threshold
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_exceeds_threshold(self):
        """Large knowledge should exceed threshold."""
        content, stats = self.km.load_for_agent(pattern=None)

        self.assertTrue(stats.exceeds_threshold)
        self.assertGreater(stats.total_tokens, stats.threshold_tokens)


class TestModuleFunctions(unittest.TestCase):
    """Tests for module-level convenience functions."""

    def test_get_counter(self):
        """get_counter should return a TokenCounter instance."""
        from token_counter import get_counter, TokenCounter
        counter = get_counter()
        self.assertIsInstance(counter, TokenCounter)

    def test_count_tokens_function(self):
        """Module-level count_tokens should work."""
        from token_counter import count_tokens
        tokens = count_tokens("Hello, world!")
        self.assertGreater(tokens, 0)

    def test_estimate_tokens_fast(self):
        """Fast estimation should work without tiktoken."""
        from token_counter import estimate_tokens_fast
        tokens = estimate_tokens_fast("Hello, world!")
        self.assertGreater(tokens, 0)

    def test_get_knowledge_manager(self):
        """get_knowledge_manager should return singleton."""
        from knowledge_manager import get_knowledge_manager
        km1 = get_knowledge_manager()
        km2 = get_knowledge_manager()
        self.assertIs(km1, km2)


def run_tests():
    """Run all tests and print results."""
    print("=" * 60)
    print("Knowledge Manager Tests")
    print("=" * 60)
    print()

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestTokenCounter))
    suite.addTests(loader.loadTestsFromTestCase(TestKnowledgeManager))
    suite.addTests(loader.loadTestsFromTestCase(TestKnowledgeManagerThreshold))
    suite.addTests(loader.loadTestsFromTestCase(TestModuleFunctions))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES: {len(result.failures)}, ERRORS: {len(result.errors)}")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
