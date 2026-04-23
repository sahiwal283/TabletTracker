"""Regex constants for receiving routes."""

import re

BATCH_VALUE_PATTERN = re.compile(r'^[A-Za-z0-9-]+$')
WORKFLOW_RECEIPT_SUFFIX_PATTERN = re.compile(
    r'-(?:seal|blister)(?:-e\d+)?$|-(?:pkg|take)-e\d+$',
    re.IGNORECASE,
)
