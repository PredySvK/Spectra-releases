### Velikost FFT bloku (FFT Size)

Určuje počet vzorků $N$ použitých pro jednu rychlou Fourierovu transformaci. Volí kompromis mezi frekvenčním a časovým rozlišením.

- **Vyšší FFT Size (např. 8192):** velmi jemné frekvenční rozlišení, ale přechodový jev se rozmaže přes delší blok.
- **Nižší FFT Size (např. 1024):** hrubší frekvenční rozlišení, ale rychlé změny (prudký rozjezd) jsou sledovány přesně.

![Stejný signál při N = 1024 a N = 16384](fft_size_compare.png)

Vlevo krátký blok sleduje rychlý přejezd, ale dva stálé sinusové signály (300 a 310 Hz) splynou. Vpravo dlouhý blok je rozliší, ale přejezd se rozmaže do schodů.

$$\Delta f = \frac{f_s}{N}, \qquad f_k = k\,\Delta f,\quad k = 0,\dots,\lfloor N/2\rfloor, \qquad T_\text{blok} = \frac{N}{f_s}$$

**Nabídka:** 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536. **Výchozí:** 4096. [Záznam](topic:raw_data/intro) musí mít alespoň $N$ vzorků, jinak výpočet skončí chybou. Nic se nedoplňuje nulami.

**Viz také:** [Okna](topic:shared/windows), [Spektrum](topic:spectrum/intro), [Spektrogram](topic:spectrogram/intro)
