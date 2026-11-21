"""
SUMO calibration and validation against observed detector counts.

- detectors: place SUMO induction loops (E1) at the mapped positions of
  the source detectors.
- e1_output: read what those loops measured in one run.
- geh: compare simulated and observed hourly counts with the GEH
  statistic.

The acceptance values are in parameters.py; how the pieces work and why
is in docs/calibration.md.
"""
