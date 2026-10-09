### Remove DC Offset

On by default in [Spectrum](topic:spectrum/intro), [Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro) and [Overall Level](topic:overall_level/intro).

The mean of the whole record is subtracted in the time domain, before blocks are cut and [windowed](topic:shared/windows). It does **not** merely zero the 0 Hz bin. A tacho or RPM channel is never touched.

**Why:** leakage. The main hump of a [Hanning window](topic:shared/windows) reaches $\pm2$ bins ($\pm12.5$ Hz at $f_s=25\,600$ Hz, $N=4096$). A DC offset left in the signal leaks energy into the neighbouring bins, for example above the default Overall Level $F_	ext{min}=10$ Hz, so the band reads higher than the vibration. Subtracting the mean first removes it at the source.

The mean is taken over the whole record, not per block, so a slow drift inside the record remains.
