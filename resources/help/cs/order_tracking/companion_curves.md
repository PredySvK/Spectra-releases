# Párované křivky řádů

Když do grafu přidáte [křivku řádu](topic:order_tracking/orders), aplikace může přidat také její spárovanou křivku z jiného kanálu téhož projektu. Hodí se to pro porovnání stejného řádu na měřeném kanálu a jeho spárovaném protějšku. Párování je volitelné: musí být nastavené v projektu a protější kanál musí být dostupný v měřeních právě načtených do Data Poolu.

## Co se přidá

Aplikace hledá spárovaný kanál pro stejný řád, jaký má nově přidaná křivka řádu. [Časový průběh](topic:raw_data/intro) může dodat křivku vypočtenou pro tento řád; importovaná křivka řádu se použije pouze tehdy, když její uložený řád souhlasí. Partner se přidá do stejného grafu běžnou cestou přetažení kanálu, takže se načte nebo vypočítá podle požadavků této cesty.

Páry fungují oběma směry: je-li kanál A spárovaný s kanálem B, přidání křivky řádu kteréhokoli z nich může najít ten druhý. Hledání prochází všechna měření aktuálně načtená v Data Poolu, nejen soubor křivky, kterou jste přidali. Pokud je v načtených souborech více odpovídajících protějšků, může se přidat každý jedinečný kandidát kanál/řád. Partner, který už je v grafu při stejném řádu, se přeskočí, takže opakované přidání nevytváří stejnou křivku znovu.

Hledání mohou zahájit jen nově přidané křivky řádů. Křivka přidaná automaticky jako partner už další hledání nespustí, takže aplikace nepokračuje po řetězci párování. Pokud později přidáte křivku sami, může hledat svého vlastního partnera.

## Když se partner nepřidá

Další křivka se nepřidá, pokud projekt nemá nastavené párování, spárovaný kanál není v aktuálně načteném měření, dostupný kanál není časový průběh ani importovaná křivka řádu nebo má importovaná křivka jiný řád. Importovaný řád, jehož soubor nelze přečíst, se přeskočí; původní křivka zůstane v grafu. Ostatní chyby se zapisují do aplikačního logu pod **Companion curves**.

Páry kanálů vytvoříte nebo upravíte podle stránky [Párování kanálů](topic:import/channel_pairing). Pár platí napříč soubory projektu; nastavení párování a formát jeho souboru popisuje tato stránka.
