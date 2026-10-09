### Energie po binech a Parsevalova invariance

**Jednoduše:** Parsevalova věta říká, že celková energie signálu je stejná, ať ji sečtete v čase, nebo ve frekvenci. FFT jen přeskládá tentýž signál do frekvenčních „přihrádek" (binů), nic nepřidá a nic neztratí. Analogie: délka vektoru se nezmění, když otočíte souřadné osy, a FFT je právě takové otočení.

**Proč ji program využívá:** Overall Level díky ní čte energii pásma přímo ze spektra, bez návratu do časového signálu a filtrování. Sečtete biny, které leží v pásmu, a odmocníte. Díky ní také výsledek nezávisí na [okně](topic:shared/windows) ani na velikosti FFT a Linear, Power i PSD dají stejný Overall Level.

## Přesně

Overall Level sčítá [energii po binech](topic:shared/amplitude_format), $P_\text{canon}[k]=c_k\lvert X[k]\rvert^2/(N\sum w^2)$, což je střední kvadrát na bin. Podle **Parsevalovy věty** je součet přes všechny biny střední kvadrát signálu a součet přes pásmo je střední kvadrát té části signálu, která leží v pásmu.

$$L^2=\sum_k b_k P_\text{canon}[k]\ \ [\text{jednotka}^2]$$

PSD je $P_\text{canon}/\Delta f$, takže $\sum \text{PSD}\cdot\Delta f$ je táž energie a pohledy Linear, Power i PSD se integrují na stejné $L$. Proto Overall Level nemá nastavení formátu. [Okno](topic:shared/windows) je už vyděleno ($\sum w^2$ ve jmenovateli), takže úroveň pásma žádnou další korekci okna nepotřebuje.

Kontrola: sinus o amplitudě $A$ hluboko v pásmu dá $L=A/\sqrt2$, ať je okno jakékoli.
