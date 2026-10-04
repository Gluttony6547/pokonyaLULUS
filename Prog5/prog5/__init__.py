"""Prog5: prediction service around the lecturer's saved LSTM price models.

Keras defaults to the TensorFlow backend, which is not installed here; the
saved artifacts load under the torch backend (verified against the research
result CSVs). The variable must be set before keras is first imported.
"""

from __future__ import annotations

import os

__version__ = "0.1.0"

os.environ.setdefault("KERAS_BACKEND", "torch")
