# =====================================================================
# FILE: signal_processing/dsp/windows.py
# =====================================================================
import numpy as np
import scipy.signal
from typing import Tuple


def generate_window(window_type: str, n_samples: int, **kwargs) -> Tuple[np.ndarray, float, float, float]:
    # Rejected up front rather than per shape: the exponential branch divides by
    # (n_samples - 1), which for a single sample produced 0/0 -> nan. nan is not
    # caught by the sum_w == 0 check below, so the factors came back as nan and
    # every downstream spectrum turned into nan with no error anywhere.
    if n_samples < 2:
        raise ValueError(f"A window needs at least 2 samples, got {n_samples}.")

    window_type_clean = window_type.lower().strip()

    if window_type_clean in ["uniform", "rectangular", "boxcar"]:
        w = np.ones(n_samples, dtype=np.float64)

    elif window_type_clean in ["hanning", "hann"]:
        w = scipy.signal.windows.hann(n_samples, sym=False)

    elif window_type_clean in ["hamming"]:
        w = scipy.signal.windows.hamming(n_samples, sym=False)

    elif window_type_clean in ["blackman"]:
        w = scipy.signal.windows.blackman(n_samples, sym=False)

    elif window_type_clean in ["flat-top", "flattop"]:
        w = scipy.signal.windows.flattop(n_samples, sym=False)

    elif window_type_clean == "tukey":
        alpha = kwargs.get("alpha", 0.5)
        alpha = max(0.0, min(1.0, float(alpha)))
        w = scipy.signal.windows.tukey(n_samples, alpha=alpha, sym=False)

    elif window_type_clean == "exponential":
        decay_val = kwargs.get("decay_value", kwargs.get("decay_param", 1.0))
        decay_val = max(1e-15, min(1.0, float(decay_val)))

        if decay_val == 1.0:
            w = np.ones(n_samples, dtype=np.float64)
        else:
            beta = -np.log(decay_val)
            w = np.exp(-beta * np.arange(n_samples) / (n_samples - 1))

    else:
        raise ValueError(f"Unsupported window type: '{window_type}'. ")

    sum_w = np.sum(w)
    sum_w2 = np.sum(w ** 2)

    if sum_w == 0 or sum_w2 == 0:
        raise ValueError("Generated window vector contains only zero weights.")

    acf = n_samples / sum_w
    ecf_linear = np.sqrt(n_samples / sum_w2)
    enbw_factor = (acf / ecf_linear) ** 2

    return w, acf, ecf_linear, enbw_factor





