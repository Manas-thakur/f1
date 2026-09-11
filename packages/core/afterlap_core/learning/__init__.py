"""AFTERLAP learning: environment, SAC training, continuation value and serving.

Module map
----------

``features``     the frozen ``energy-v1`` encoder, driven by ``ENERGY_V1``
``actions``      the two bounded soft preferences and their reachable bounds
``reward``       reward revision ``objective-v1`` and its potential shaping
``bridge``       simulator observation -> belief -> rule context -> features
``env``          the Gymnasium environment at a one-second policy cadence
``config``       readers for ``configs/learning/``
``value``        the ordinary continuation-return ensemble
``calibration``  the isotonic probability calibrator and its refusals
``dataset``      forecast/realisation and continuation collection from episodes
``prediction``   one serving surface for every learned prediction
``serving``      the frozen bundle, its hashes and the loader that refuses
``promotion``    ``promote_bundle``, whose default answer is no
``architecture``  layer tables and trainable-parameter counts, read off the modules
``policy``       the frozen actor, rebuilt from bundle weights and made runnable
``packaging``    a verified checkpoint becomes a loadable bundle with a real card
``jobs``         the operator entry points behind the coordinator CLI
``checkpoints``  atomic checkpointing and resume
``callbacks``    training metrics and the non-finite-loss guard
``train_sac``    SB3 SAC training, resume and the throughput benchmark

What this package will not do
-----------------------------

* It does not replace a constraint. Preferences are soft; the planner still
  returns a legal plan and the independent checker's verdict is final.
* It does not promote itself. Promotion needs frozen thresholds and a real
  benchmark report, and refuses without them.
* It does not report a training result it did not observe. A smoke run is
  labelled a smoke run wherever it appears.
* Nothing here is a measured result about a real car, circuit or race.
"""

from __future__ import annotations
