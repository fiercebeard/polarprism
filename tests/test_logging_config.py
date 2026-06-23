from __future__ import annotations

import logging

from logging_config import LOGGER_NAME, setup_logging


class TestSetupLogging:
    def teardown_method(self):
        # Reset the logger between tests so handlers don't accumulate.
        logger = logging.getLogger(LOGGER_NAME)
        for h in list(logger.handlers):
            logger.removeHandler(h)
            h.close()

    def test_attaches_two_handlers(self, tmp_path):
        setup_logging(error_log_dir=str(tmp_path))
        logger = logging.getLogger(LOGGER_NAME)
        assert logger.level == logging.INFO
        # stderr + rotating file.
        assert len(logger.handlers) == 2
        types = {type(h).__name__ for h in logger.handlers}
        assert "StreamHandler" in types
        assert "RotatingFileHandler" in types

    def test_creates_error_log_file_on_emit(self, tmp_path):
        setup_logging(error_log_dir=str(tmp_path))
        logger = logging.getLogger(LOGGER_NAME)
        logger.error("test message %s", 42)
        # Flush so the file is written.
        for h in logger.handlers:
            h.flush()
        log_path = tmp_path / "error.log"
        assert log_path.exists()
        content = log_path.read_text()
        assert "ERROR" in content
        assert "test message 42" in content

    def test_falls_back_to_stderr_only_if_dir_unwritable(self, tmp_path):
        # Point at a path under a file (not a dir) so makedirs fails.
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        unwritable = str(blocker / "subdir")
        setup_logging(error_log_dir=unwritable)
        logger = logging.getLogger(LOGGER_NAME)
        # Only the stderr handler should be present.
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_idempotent_no_duplicate_handlers(self, tmp_path):
        setup_logging(error_log_dir=str(tmp_path))
        setup_logging(error_log_dir=str(tmp_path))
        logger = logging.getLogger(LOGGER_NAME)
        assert len(logger.handlers) == 2

    def test_propagate_false(self, tmp_path):
        setup_logging(error_log_dir=str(tmp_path))
        assert logging.getLogger(LOGGER_NAME).propagate is False
