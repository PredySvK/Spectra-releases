### Remove DC Offset

Ve výchozím stavu zapnuto ve [Spektru](topic:spectrum/intro), [Spektrogramu](topic:spectrogram/intro), [Order Trackingu](topic:order_tracking/intro) a [Overall Levelu](topic:overall_level/intro).

Průměr celého záznamu se odečte v časové oblasti před řezáním bloků a [okénkováním](topic:shared/windows). **Neznamená** to pouhé vynulování binu 0 Hz. Kanál tacha či RPM se nikdy neupravuje.

**Proč:** leakage. Hlavní hrb [okna Hanning](topic:shared/windows) sahá do $\pm2$ binů ($\pm12{,}5$ Hz při $f_s=25\,600$ Hz, $N=4096$). DC offset ponechaný v signálu prosakuje energii do okolních binů, např. nad výchozí $F_	ext{min}=10$ Hz v Overall Levelu, takže pásmo ukazuje víc než skutečná vibrace. Odečtení průměru předem to odstraní u zdroje.

Průměr se bere z celého záznamu, ne z každého bloku, takže pomalý drift uvnitř záznamu zůstává.
