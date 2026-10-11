"""Structured logging configuration for SAP CDS Intelligence & Automation Platform."""

import logging
import sys
from typing import Optional


def setup_logging(log_level: Optional[str] = "INFO") -> None:
    """Configures structured console logging with timestamp and correlation metadata."""
    level = getattr(logging, (log_level or "INFO").upper(), logging.INFO)
    log_format = "%(asctime)s | %(levelname)-8s | [%(name)s] [%(filename)s:%(lineno)d] - %(message)s"

    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


logger = logging.getLogger("sap_cds_platform")
