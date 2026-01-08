import logging
import unittest

from utils import logging_utils
from utils.logging_utils import build_logging_config, get_tagged_logger, mask_db_url


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        self.records.append(record)


class TestLoggingUtils(unittest.TestCase):
    def test_build_logging_config_has_expected_handlers_and_filters(self):
        cfg = build_logging_config(job_name="jobtest")
        self.assertIn("handlers", cfg)
        self.assertIn("stdout", cfg["handlers"])
        self.assertIn("stderr", cfg["handlers"])
        self.assertIn("filters", cfg)
        # job_name filter should carry configured job
        self.assertEqual(cfg["filters"]["job_name"]["job_name"], "jobtest")

    def test_get_tagged_logger_injects_tag(self):
        handler = _ListHandler()
        logger = get_tagged_logger("foo.bar", tag="custom_tag")
        base_logger = logger.logger
        base_logger.setLevel(logging.DEBUG)
        base_logger.addHandler(handler)
        base_logger.propagate = False

        logger.info("hello world")

        self.assertTrue(handler.records)
        record = handler.records[-1]
        self.assertEqual(record.tag, "custom_tag")

        # cleanup
        base_logger.removeHandler(handler)

    def test_setup_logging_override_applies_filters(self):
        root = logging.getLogger()
        orig_handlers = root.handlers[:]
        orig_level = root.level
        try:
            logging_utils.setup_logging(level="INFO", job_name="jobtest", override_existing=True)
            self.assertTrue(root.handlers)
            # Check that at least one handler has JobNameFilter applied
            self.assertTrue(
                any(
                    any(f.__class__.__name__ == "JobNameFilter" for f in h.filters)
                    for h in root.handlers
                )
            )
        finally:
            root.handlers = orig_handlers
            root.setLevel(orig_level)
            root.propagate = True
            logging_utils._CONFIGURED = False  # reset for other tests


class TestMaskDbUrl(unittest.TestCase):
    def test_masks_username_and_password_in_netloc(self):
        url = "postgresql://user:secret@host:5432/db"
        masked = mask_db_url(url)
        self.assertEqual(masked, "postgresql://***:***@host:5432/db")

    def test_leaves_urls_without_credentials(self):
        url = "sqlite:///tmp/db.sqlite"
        self.assertEqual(mask_db_url(url), url)

    def test_masks_only_sensitive_query_params(self):
        url = "postgresql://host/db?password=abc&foo=bar&api_key=xyz&Param=ok"
        masked = mask_db_url(url)
        self.assertEqual(masked, "postgresql://host/db?password=%2A%2A%2A&foo=bar&api_key=%2A%2A%2A&Param=ok")

    def test_masks_username_even_without_password(self):
        url = "postgresql://user@host/db"
        masked = mask_db_url(url)
        self.assertEqual(masked, "postgresql://***@host/db")

    def test_returns_original_on_unparseable_input(self):
        bad_url = "not a url"
        self.assertEqual(mask_db_url(bad_url), bad_url)


if __name__ == "__main__":
    unittest.main()
