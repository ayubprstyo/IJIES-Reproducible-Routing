# Synthetic Demo Data

**This data is entirely SYNTHETIC (randomly generated), not derived from
any real operational or commercial source.** It exists solely so that the
computational code path (src/data.py, src/simulator.py, src/search.py,
src/liu_alns.py) can be smoke-tested end-to-end without requiring any
real or de-identified derived commercial data.

Do NOT use this data for any statistical claim about the manuscript's
actual results -- for that, see data_deidentified/experiment_outputs/,
which contains the real corrected experiment outcomes (aggregated,
de-identified, containing no customer-level operational detail).

Generated with numpy.random.default_rng(12345); includes one deliberately
oversized stop (DEMO_C_BIG) so the split-stop logic and its regression
tests can be exercised on synthetic data too.
