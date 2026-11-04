"""SQL pause (tool-call) duration distributions, shared by the G1 simulator and the G3 replayer.

"redshift": Redshift-like query times, pinned at the quantiles the plan uses
(p50 0.1 s, p90 1.8 s, p99 26 s), with assumed tails p0 = 5 ms and p100 = 60 s.
Between the knots the inverse CDF is log-linear, so it's piecewise log-uniform.
"ms": millisecond-only lookups, 2-50 ms log-uniform (the "no long queries" control).
"""
import numpy as np

KNOTS = {
    "redshift": ([0.0, 0.50, 0.90, 0.99, 1.0], [0.005, 0.1, 1.8, 26.0, 60.0]),
    "ms": ([0.0, 1.0], [0.002, 0.050]),
}


def sample(rng, n=None, mix="redshift"):
    """Draw pause durations in seconds."""
    q, t = KNOTS[mix]
    u = rng.random(n)
    return np.exp(np.interp(u, q, np.log(t)))


def quantile(p, mix="redshift"):
    q, t = KNOTS[mix]
    return float(np.exp(np.interp(p, q, np.log(t))))


def mean(mix="redshift"):
    """Exact mean of the piecewise log-uniform distribution."""
    q, t = KNOTS[mix]
    m = 0.0
    for (q0, q1), (a, b) in zip(zip(q, q[1:]), zip(t, t[1:])):
        m += (q1 - q0) * (b - a) / np.log(b / a)  # mean of log-uniform on [a, b]
    return m


if __name__ == "__main__":
    for mix in KNOTS:
        print(mix, "mean %.3f s" % mean(mix),
              " ".join("p%g=%.3g" % (100 * p, quantile(p, mix)) for p in (0.1, 0.5, 0.9, 0.99)))
