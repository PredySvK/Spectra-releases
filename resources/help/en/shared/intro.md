# Common analysis settings

[Spectrum](topic:spectrum/intro), [Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro) and [Overall Level](topic:overall_level/intro) cut the signal into blocks, window each block, take an FFT and scale the result. These pages describe the settings they share.

| Setting | Page | Default |
|---|---|---|
| FFT size $N$ | [FFT size](topic:shared/fft_size) | 4096 |
| Window | [Windows](topic:shared/windows) | Hanning |
| Format and amplitude | [Amplitude format](topic:shared/amplitude_format) | Linear, RMS |
| Step, sweep, hysteresis | [Tacho tracking](topic:shared/tracking) | 50 RPM, Up, 10 RPM |
| Remove DC Offset | [Remove DC Offset](topic:shared/remove_dc) | on |

A result is stored as **energy per bin** $P_\text{canon}$ (squared unit, for example g²). Linear, Power, PSD, RMS and Peak are [views](topic:shared/amplitude_format) computed from it when the result is shown, so switching them never recomputes the FFT.
