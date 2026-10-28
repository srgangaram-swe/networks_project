# Synthetic request captures

Both JSON files contain invented observations for validator tests, not measured
network traffic. The valid example has two requests, spaced 500 ms apart, with
1 ms RTT and 1 microsecond of sender delay. The invalid example repeats request
ID 0 in the second record. A validator must reject it even though its reported
summary counts look plausible.

The larger bundle fixtures in tests/fixtures.py are generated only inside
temporary test directories. Do not use any fixture as experiment evidence.
