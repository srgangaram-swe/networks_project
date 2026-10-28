# Synthetic request captures

Both JSON files contain invented observations for validator tests, not measured
network traffic. The valid example has two requests, spaced 500 ms apart, with
1 ms RTT and 1 microsecond of sender delay. The invalid example repeats request
ID 0 in the second record. A validator must reject it even though its reported
summary counts look plausible.

The larger bundle fixtures in tests/fixtures.py are generated only inside
temporary test directories. Do not use any fixture as experiment evidence.

To inspect complete examples, generate them into a new local directory:

    .venv/bin/python -m tests.fixtures --output .local/bundle-examples
    .venv/bin/python scripts/validate_bundle.py .local/bundle-examples/valid-synthetic
    .venv/bin/python scripts/validate_bundle.py .local/bundle-examples/invalid-duplicate

The first validator command succeeds; the second returns status 2 because a
request identifier is repeated. Its hashes were recomputed after the deliberate
corruption, so rejection tests the request contract rather than only the file
digest. Both bundles are labeled synthetic_fixture, and the diagnostic exporter
rejects them. Generation refuses an existing output directory.
