# Aktualizace

Spectra může zkontrolovat, zda je dostupná novější stabilní verze, a v nainstalované aplikaci pro Windows stáhnout a spustit její instalátor. Kontrolu lze spustit ručně v Settings nebo ji nechat proběhnout jednou po spuštění aplikace.

## Kontrola aktualizace

Na záložce **Settings** zvolte **Check for Updates**. Po spuštění aplikace Spectra provede stejnou kontrolu poté, co se zobrazí její okno. Informace o nejnovější verzi čte z GitHubu na pozadí, takže okno zůstává responzivní.

Spectra nabídne aktualizaci pouze tehdy, když je vydaná verze novější než používaná, není označená jako draft ani prerelease a obsahuje odpovídající instalační soubor `Spectra-<version>-setup.exe`. Nabídka zobrazí poznámky k vydání, pokud jsou k dispozici; jinak uvede **No patch notes provided.** Pokračujte volbou **Update now**, nebo zvolte **Later** a pokračujte v práci. **Later** je výchozí volba.

Pokud ruční kontrola nenajde novější vyhovující verzi, Spectra zobrazí **You are up to date.** Kontrola po spuštění zůstane bez zprávy, pokud není co nabídnout. Při chybě ruční kontroly se zobrazí upozornění; neúspěšná kontrola při spuštění zůstane bez zprávy. Pokud na GitHubu není žádná stabilní verze, aplikace to považuje za stav bez dostupné aktualizace. Pokud ruční kontrola běží ve chvíli, kdy stisknete tlačítko znovu, druhá se nespustí a její výsledek se zobrazí po dokončení první. Během stahování další ruční kontrola oznámí, že se aktualizace už stahuje.

## Co je nového

Když není otevřený žádný projekt, úvodní stránka pod seznamem **Recent** ([projekty](topic:general/projects)) zobrazuje posouvatelný seznam **What's new**: každou vydanou verzi ve tvaru `verze - datum vydání` a seznam změn. Pod změnou se zobrazují i její snímky obrazovky. Funguje i offline, seznam je součástí aplikace.

## Stažení a zrušení

Instalace přímo z aplikace je dostupná pouze v nainstalované verzi Spectra pro Windows. Pokud nabídku přijmete v jiném prostředí, Spectra vysvětlí, že tato funkce je dostupná v nainstalované verzi Spectra pro Windows; instalátor tam nestáhne.

Po volbě **Update now** v nainstalované aplikaci Spectra stáhne instalátor do dočasného souboru. Stahování se zobrazí mezi [běžícími úlohami](topic:jobs/intro) s průběhem a tlačítkem **Cancel**. Zrušit ho lze na stavovém proužku úloh, nebo výběrem úlohy v panelu *Jobs* a volbou **Cancel Selected** (případně **Cancel All**). Neúspěšné nebo zrušené stažení se odstraní. Při chybě stahování Spectra zobrazí **Update download failed. Please try again later.**

## Zavření Spectra a instalace

Po dokončení stahování Spectra před spuštěním instalátoru provede běžné zavření aplikace:

1. Pokud stále běží uživatelem spuštěná dávková úloha, potvrďte její zrušení a zavření aplikace.
2. Pokud [projekt](topic:general/projects) obsahuje neuložené změny, zvolte **Save**, **Discard**, nebo **Cancel**. U projektu s načtenými daty, který ještě nebyl uložen, se také nabídne uložení. Volba **Cancel** nebo neúspěšné uložení ponechá Spectra otevřené a instalaci nespustí.
3. Spectra uloží nastavení okna a rozložení, zavře pracovní plochu a potom spustí stažený instalátor.

Instalátor běží bez dalších dialogů ve složce, která obsahuje aktuální spustitelný soubor Spectra. Požádá také o restart aplikace po dokončení instalace. Pokud instalátor nelze spustit, Spectra zobrazí upozornění a zavře se bez aktualizace; pro nový pokus aplikaci znovu spusťte.

Pokud kontrola nebo stahování selže, zkuste to později znovu s funkčním připojením k internetu. Ovládání úloh popisují [Úlohy](topic:jobs/intro); uložení práce najdete v [Projektech](topic:general/projects).
