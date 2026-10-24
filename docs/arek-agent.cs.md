# arek: zadání pro AI agenta

Pomáháš s reverzním inženýrstvím disketové hry z Amigy pomocí **amiga-re-kit** (příkaz
`arek` a server `arek-mcp`). Než na cokoli sáhneš, přečti celý tento soubor. Ulož ho do
složky projektu jako `CLAUDE.md` (Claude Code ho načte při startu), nebo ho vlož do první
zprávy kterémukoli programovacímu agentovi.

## Pravidla

1. **Jediný zdroj pravdy je originál.** Každé tvrzení je měření: adresa, hash, diff, snímek
   obrazovky. Nikdy nehádej z názvu hry, z videa ani z toho, co si o hře pamatuješ.
2. **Herní data zůstávají mimo repozitář.** Žádné `.adf`, žádný Kickstart ROM, žádné otisky
   paměti ani vytažená grafika v gitu. Cesty k nim žijí jen v git-ignorovaném `local.conf`;
   vytažená data patří do `build/` (git-ignorováno).
3. **Obraz diskety nikdy neměň.** Čti ho; pracuj na kopiích.
4. **Zapisuj, co jsi změřil, s přesným příkazem**, aby to mohl zopakovat někdo, kdo hru
   nikdy neviděl. K měřením zaznamenej verzi kitu a hash dekodéru (`kit_info`,
   `arek --version`).
5. **Když nástroj odmítne, zastav se a nahlas to.** Dekodér vyhodí chybu na instrukci, kterou
   nemodeluje, rozbalovač odmítne blok, který neprojde ověřením: to je výsledek, ne překážka.
   Neobcházej to odhadem. Zapiš to do `docs/KIT-GAPS.md` s nejmenším vstupem, který to
   vyvolá.

## Příprava (jednou)

- `pip install "amiga-re-kit[mcp]"` (Python 3.11 nebo novější). `arek --help` vypíše příkazy,
  `arek <příkaz> --help` jejich volby.
- `arek init .` vytvoří `local.conf` a `.gitignore`. Do `ADF1=` zapiš cestu k obrazu diskety
  (`ADF2=` pro druhou disketu). Cestu si vyžádej od uživatele; neprohledávej kvůli ní disk.
- MCP: `.mcp.json` v projektu s obsahem
  `{ "mcpServers": { "arek": { "command": "arek-mcp" } } }` ti dá stejné přístroje jako
  nástroje (26). Nejdřív zavolej `kit_info`.
- Volitelně, pro měření proti běžící hře: bezhlavé sestavení vAmigy (`docs/HEADLESS.md`
  v kitu) a Kickstart ROM, který uživatel vlastní; `VAHL=` a `ROM=` v `local.conf`. Bez nich
  kroky 0 až 4 níže fungují také.

## Postup, v tomto pořadí

0. **Inventura.** `arek adf info <adf>`: velikost, SHA-256, typ a kontrolní součet boot bloku.
   Hash zapiš do `docs/disk.md`; každé pozdější tvrzení se vztahuje přesně k tomuto obrazu.
   Crackované obrazy se mezi sebou liší.
1. **Podívej se, než začneš číst.** `arek adf map <adf>` a `arek adf regions <adf>`: kde leží
   kód, zabalená data, grafika a prázdné sektory. Popiš disketu dřív, než dekóduješ jedinou
   instrukci.
2. **Zaváděcí řetězec.** `arek dis <adf> --base 0 --walk 0xc` vypíše, kam boot blok dosáhne;
   sleduj loader k další fázi (`arek adf track`, `arek adf sector`). Disketa s AmigaDOS:
   `arek adf ls`, `arek adf cat`, `arek adf extract`.
3. **Packery.** `arek scan <soubor>` najde známé signatury a bloky Bytekilleru ověřené
   rozbalením; `arek pp20`, `arek bytekiller`, `arek atn`, `arek t2` je rozbalí. Neznámý
   packer znamená přečíst rozbalovací rutinu vedle loaderu, ne hádat formát.
4. **Kód.** `arek walk --base <adresa> --start <vstup>` sleduje graf toku a hlásí jeho hranice;
   `arek hwscan` oddělí rutiny pracující jen s RAM od těch, které řídí Agnus, Denise a Paulu;
   `arek xref` říká, kdo co čte a zapisuje; `arek hunk` čte spustitelné soubory AmigaDOS;
   `arek copper` disassembluje copper listy.
5. **Rekompiluj a ověř.** `arek recomp --base <adresa> --func <start:konec>` přeloží jednu
   rutinu do C i s ověřovacím driverem. Spusť ji nad otiskem RAM originálu (`arek bpstate`)
   a porovnej přes `arek diff`. Shoda, nebo není hotovo. `arek recomp --profile` říká, na
   kterých rutinách záleží výkonově.
6. **Ověř proti skutečné hře.** `arek shot` pořizuje deterministické snímky ve známých
   snímcích se skriptovaným vstupem; `arek trace` zaznamenává registry, vstupy a provoz na
   sběrnici; `arek render` vykreslí snímek z chip RAM, aby šel porovnat pixel po pixelu.

## Co odevzdat

- `docs/disk.md`: inventura, mapa, oblasti, nalezené packery, zaváděcí řetězec, u každého
  příkaz a jeho výsledek.
- `docs/code.md`: nalezené rutiny, hranice hardwaru, co je ověřené a jak.
- `docs/KIT-GAPS.md`: co kit nedokázal, s reprodukovatelným vstupem.
- Krátký seznam otevřených otázek pro uživatele: která verze diskety, který ROM, co stavět
  jako první.

Hlas se v jazyce uživatele, příkazy a názvy souborů uváděj přesně tak, jak jsi je spustil,
a jasně odděl, co je změřené a co je ještě otevřené.
