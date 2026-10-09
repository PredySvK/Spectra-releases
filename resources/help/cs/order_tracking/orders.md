### Extrakce řádů

## Pohyblivé pásmo

Při triggeru s otáčkami $\text{RPM}$ je pásmo řádu $n$ vystředěno a dimenzováno takto:

$$f_n=\frac{n\cdot\text{RPM}}{60},\qquad W_n=\max\!\Bigl(\Delta O\cdot\frac{\text{RPM}}{60},\ \ B\,\Delta f\Bigr),\qquad \Bigl[f_n-\tfrac{W_n}{2},\ f_n+\tfrac{W_n}{2}\Bigr]$$

s dolní hranou oříznutou na 0 Hz. $\Delta O$ je **Order Width** v řádech, $\Delta f=f_s/N$ šířka binu a $B$ **šířka hlavního hrbu [okna](topic:shared/windows) v binech**, změřená z okna samotného:

| Okno | Rectangular | Hanning, Hamming | Blackman | Flat-top |
|---|---|---|---|---|
| $B$ [biny] | 2 | 4 | 6 | asi 10 |

Pásmo tedy není nikdy užší než hlavní hrb: sinusová složka řádu pak drží veškerou energii v pásmu, ať je Order Width jakkoli malá. S výchozími hodnotami ($f_s=25\,600$ Hz, $N=4096$, tj. $\Delta f=6{,}25$ Hz, Hanning, $\Delta O=0{,}2$) je pásmo široké 25 Hz do $0{,}2\cdot\text{RPM}/60=25$ Hz, tedy do 7500 ot/min, a poté roste s otáčkami.

## Hodnota

Biny se váží podílem své šířky uvnitř pásma ([Zlomkové biny](topic:overall_level/band)):

$$A_n=\sqrt{\sum_k w_{n,k}\,P_\text{canon}[k]},\qquad w_{n,k}\in[0,1]$$

Podle Parsevala je součet střední kvadrát, takže $A_n$ je RMS řádu v jednotce signálu.

**Kdy hodnota chybí.** Křivka má mezeru (NaN) v každém triggeru, kde $f_n<\Delta f$ (pod rozlišením FFT) nebo $f_n>f_s/2$. Pokud je *každý* požadovaný řád všude mezerou, výpočet se odmítne se zprávou uvádějící rozsah otáček a rozlišení FFT; použijte menší FFT nebo nižší řády.

## Overall Level + Residual

Se zaškrtnutým **Overall Level + Residual** dá stejné $P_\text{canon}$ jedním průchodem ještě dvě křivky:

- **OAL**: [Overall Level](topic:overall_level/intro) výchozího pásma, 10 Hz až Nyquist souboru ($F_\text{min}=10$ Hz, Full Bandwidth). Pásmo se zde nedá změnit. Používá [FFT](topic:shared/fft_size), [okno](topic:shared/windows), Step, Sweep ([tracking](topic:shared/tracking)), Hysterezi a Remove DC této záložky.
- **Residual**: energie tohoto pásma **mimo** pásma všech vybraných řádů.

Nechť $b_k$ je podíl binu $k$ uvnitř pásma OAL a $m_k$ podíl pokrytý **sjednocením** pásem řádů (oříznutým na pásmo OAL):

$$\text{OAL}=\sqrt{\sum_k b_k P_k},\qquad \text{Explained}=\sqrt{\sum_k m_k P_k},\qquad \text{Residual}=\sqrt{\sum_k (b_k-m_k)\,P_k}$$

$$\text{Explained}^2+\text{Residual}^2=\text{OAL}^2$$

Platí to v každém bodě a Residual není nikdy záporný.

### Příklad

Rozjezd převodovky, jeden bod při 3000 ot/min: hřídel je na 50 Hz, **Target Orders** `2, 4`. Řád 2 je na 100 Hz, řád 4 na 200 Hz; každé pásmo je široké 25 Hz (hlavní hrb), takže se pásma nedotýkají. Nechť integrály dají

| | Energie [g²] | Úroveň [g RMS] |
|---|---|---|
| OAL (10 Hz – Nyquist) | 1,00 | 1,00 |
| Řád 2 | 0,64 | 0,80 |
| Řád 4 | 0,16 | 0,40 |
| Explained (sjednocení) | 0,80 | 0,89 |
| **Residual** | **0,20** | **0,45** |

Oba řády vysvětlují 80 % energie v pásmu. Zbylých 20 % (Residual 0,45 g) je při těchto otáčkách něco jiného: rezonance, šum, řád, který jste nevybrali. Je-li Residual největší křivkou grafu, hledejte, co chybí, například pomocí [Dominantních řádů](topic:evaluation/dominant_orders).

### Proč křivky řádů prostě neodečíst?

$\sqrt{\text{OAL}^2-\sum A_n^2}$ vypadá jako totéž, ale společnou energii počítá dvakrát. Při nízkých otáčkách se pásma sousedních řádů překrývají: při 600 ot/min je hřídel na 10 Hz, řády 1 a 2 leží na 10 a 20 Hz a obě pásma jsou široká 25 Hz, takže pokrývají převážně stejné biny. Součet čtverců pak přesáhne OAL a rozdíl se stane záporným. Residual používá sjednocení, takže každý bin se počítá jednou. Řád, který v triggeru nemá hodnotu (mezery výše), tam nic nemaskuje. Přepínač [RMS / Peak](topic:shared/amplitude_format) škáluje Residual stejně jako řády.

Jen živý dock řádů: Overall Level + Residual není k dispozici v [dávce](topic:batch/intro), v bloku workflow ani v uloženém h5 ([Result Pool](topic:results/intro)).
