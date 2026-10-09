### FFT Size (Block Size)

Defines the number of samples $N$ used for one Fast Fourier Transform. It sets the trade-off between frequency resolution and time resolution.

- **Higher FFT size (e.g. 8192):** very fine frequency resolution, but a transient is smeared over a longer block.
- **Lower FFT size (e.g. 1024):** coarse frequency resolution, but fast changes (a rapid run-up) are followed closely.

![The same signal at N = 1024 and N = 16384](fft_size_compare.png)

On the left the short block follows the fast sweep, but the two steady sine signals (300 and 310 Hz) merge. On the right the long block separates the sine signals, but the sweep is smeared into steps.

$$\Delta f = \frac{f_s}{N}, \qquad f_k = k\,\Delta f,\quad k = 0,\dots,\lfloor N/2\rfloor, \qquad T_\text{block} = \frac{N}{f_s}$$

**Choices:** 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536. **Default:** 4096. The [record](topic:raw_data/intro) must be at least $N$ samples long, otherwise the computation stops with an error. Nothing is zero-padded.

**See also:** [Windows](topic:shared/windows), [Spectrum](topic:spectrum/intro), [Spectrogram](topic:spectrogram/intro)
