# Inventura zobrazení (kit 0.9.11, 2026-11-01)

Hloubková kontrola vrstvy „plynulý obraz“ kitu a jejího použití ve hrách (Superfrog, Alien Breed II, Alien Breed SE92).
Zadání: zjistit, zda všechno funguje, co je zbytečné nebo kontraproduktivní, navrhnout zjednodušení. Fakta ze
zdrojáků kitu, z kánonu `docs/WB-PLYNULOST.md` a z odpovědí relací her (příloha). Nic z toho zatím není nakódováno.

## 1. Co kit má

| vrstva | modul | verze | řádků | testů | obsah |
|---|---|---|---|---|---|
| hodiny | `wb-takt.js` | 1.2 | 144 | 5 | permity snímků hry z rAF, zámek na k × 50 Hz, časová osa, páry pro mezipolohy, zpoždění latC/latO (latO adaptivní), extrapolace, reset |
| presenter | `wb-obraz.js` | 1.5 | 429 | 13 | jedno plátno WebGL2 nebo 2D, geometrie v pixelech zařízení, CRT, filtry, poměr pixelu, menu |
| scéna | `wb-scene.js` | 1.6.1 | 539 | 17 | jeden záznam na snímek hry → GPU kompozice + CPU reference (0 neshod); volby níže |
| zvuk | `wb-zvuk*.js` | 1.0 / 1.1 | — | 6+ | AudioWorklet nad kruhem ve sdílené paměti (zásoba 30 ms) nebo zprávy |
| engine | `arek_host_engine.c --thread` | — | — | — | hra ve vlákně s permity (futex); korutina ASYNCIFY jako záloha |
| měření | `arek web smooth`, `arek web replay` | 1.4 / H | 404 | 14 | limity kánonu (zahozené snímky, chvění, chybějící páry, odezva, zvuk); důkaz, že displej hru nemění |

Volby scény: `camMean`, `softClamp`, `smoothY`, `pairOlder`, `jumpMax`, `passMax`, `fixedAxis`, `x17`, `subpixel`,
`extrapolate` (jen kamera); v záznamu `hud.under`, `sprites[].screen/id`, `objects[].ox/oy/steady`, `window.over`;
pomocník `unexplained()`. Háčky stránky WBLONGRUN 1.1–1.5 (15 háčků, většina volitelných).

## 2. Funguje to?

Ano, měřeno a zapsáno v kánonu: Superfrog i Alien Breed II 0 neshod GPU proti referenci (miliony bodů, i s posunem
pod pixel), 0 zahozených snímků, chvění kamery 0,03 px, replay EQUAL na 50/60/120/144 Hz v Chromiu i WebKitu, zvuk
ve vlákně 0 výpadků při 10 zátěžích. Žádný modul není rozbitý.

## 3. Zjištění

### 3.1 Modul hodin (wb-takt) nepoužívá žádná hra

Kánon říká „vrstva 3 = kit“. Skutečnost: Superfrog má vlastní takt (rAF povoluje snímky workeru, pevná zpoždění
28 / 48 ms, bez zámku a extrapolace); Alien Breed II má vlastní PACE (předloha wb-taktu: ahead 2, latC 20 / 30, latO
pevně 40, zámek na k × 50 Hz). wb-takt běží jen na syntetických stránkách kitu. Superfrog zároveň hlásí jako slabé
místo přesně to, co wb-takt se zvukem ze sdílené paměti řeší: při zaseknutí hlavního vlákna vyteče zvukový buffer
25–30 ms (Alien Breed II má s modelem kitu 0 výpadků). Alien Breed II dál nepoužívá wb-zvuk-worklet/out, wb-atn ani
wb-content – má starší vlastní kopie.

### 3.2 Volby scény: co se používá

| volba | Superfrog | Alien Breed II | verdikt |
|---|---|---|---|
| camMean 20 | ano (přepínač „svislé vyhlazení“) | ne | nechat |
| softClamp, smoothY | ne (odstraněno při 1.2) | ne | zrušit |
| pairOlder 2, passMax 100, jumpMax 40 | ano | výchozí | nechat; sepsat tabulku pravidel |
| fixedAxis | ano (mezihra, svislá kamera stojí) | ne | nechat |
| x17 | ne | ne | čistá funkce, neškodí |
| hud.under | ano | ne | nechat |
| window.over | ano (vrstva enginu „zobrazené ≠ čisté“) | ne (záznam = engine, 0 neshod) | nechat |
| subpixel | jen slepý test A/B | zapnuto ve vývoji | čeká na slepý test |
| objects[].steady | ne | jen posunutý záblesk | nechat |
| unexplained() | ne (zásoba) | ne | nechat |

### 3.3 Zpoždění

V ostré verzi: Superfrog 28 / 48 ms pevně, Alien Breed II 20 / 40 ms pevně. Adaptivní latO 60–120 ms (wb-takt i PACE)
neběží nikde. Alien Breed II ji zapíná jen v režimu wb-scene, protože scéna nedopočítává objekty za poslední průchod
(jejich engine ano, o jeden krok). Kratší cesta: dopočet objektů o jeden průchod přímo ve scéně (`of` až 1 +
extrapolate) → pevných 40 ms všude, adaptace zmizí.

### 3.4 Duplicity ve hrách

- Superfrog: dvě kreslení (modul kitu + starší `web/scene.js`), engine kvůli tomu plní vrstvy pro obě; zpoždění
  zapsaná dvakrát; mrtvý přepínač „nepřátelé v pixelech monitoru“ (modul to dělá vždy); „míchání snímků“ jen pro
  starou cestu; nejdražší JS na snímek je přestavba objektů z vrstvy ol + kopie bob/spr do arény (neměřeno).
- Alien Breed II: dvě cesty Vylepšeno (view.h + gl.js a wb-scene, záměrně do rozhodnutí); vlastní PACE, audio
  worklet, atn, content místo modulů kitu; HUD se kopíruje do každého záznamu (2 × ~100 kB).
- Alien Breed SE92: všechno vlastní, kit 0.6.3 (viz jeho rozbor).

### 3.5 Drobnosti v kitu

- `_hud` rozšiřuje HUD na CPU při každém kreslení – stačí cache podle objektu HUD.
- Úzké mapy: scéna centruje kameru na 0,5 bodu, engine Alien Breed II celočíselně (1 sloupec rozdíl) – sjednotit.
- 2D cesta bez WebGL kreslí referenci na CPU každý snímek: při 1,6 M bodů desítky ms, hrát se na tom nedá – je to
  diagnostika, ne záloha.
- Měření `arek web smooth` záměrně nepočítá kroky v pixelech zařízení (2-2-1) jako chvění (G43); proto nemá číslo
  pro posun pod pixel – jen slepý test.
- wb-takt má 5 testů; je to nejcitlivější modul (zámek, pauza, přeběh hry před permity, reset).
- `extrapolate` v taktu (f až 2) může při zastavení kamery přestřelit; výchozí vypnuto, nikdo ho nezapíná.

### 3.6 Slabá místa her mimo KIT-GAPS (z jejich odpovědí)

Superfrog: zvuk při zaseknutí hlavního vlákna; „mimo seznam“ jen v původním okně (v okrajích výřezu chybí, podezření
řetěz koule 5-2); aktivace objektů v okrajích (opravují, chyba jejich rozšíření). Alien Breed II: problikávání E/O v
Safari (přijato); záblesk u hlavně posouván bez podmínky „nemá pokračování“; dotykové zařízení bez klávesnice pro
jméno; arek-play má starý build; korutinový engine 30 min překladu, může být „stale“.

## 4. Návrh (pořadí podle přínosu)

1. **Zmrazit přidávání funkcí zobrazení.** Zbývají dvě: přechod režimů z kitu (wb-scene 1.7) a dopočet objektů o
   průchod (3.3). Pak „1.0“ vrstvy zobrazení: jen opravy mezer.
2. **Hry zruší druhé cesty** po přechodu z kitu: Superfrog starý scene.js + mrtvé přepínače + dvojí zpoždění;
   Alien Breed II view_render-mezipolohy, gl.js, VW_SPLIT. Jedno vydání za přepínačem, pak smazat.
3. **wb-takt do her** (rozhodnutí uživatele): Superfrog kvůli zámku a zvuku bez výpadků, Alien Breed II kvůli
   duplicitě PACE. Alternativa: wb-takt degradovat na ukázku a kánon přepsat.
4. **Úklid kitu:** softClamp/smoothY pryč; adaptivní latO pryč (po 3.3); `_hud` cache; centrování úzkých map;
   tabulka pravidel (jumpMax, pairOlder, passMax, takt.pass, reset) na jednom místě; stránka „recept pro novou hru“
   (15 řádků) vedle kroniky kánonu.
5. **Měření:** informativní metrika kroků v pixelech zařízení (čísla ke slepému testu); syntetické testy wb-takt
   (přeskočený snímek, přepnutí zámku, pauza/obnovení, reset uprostřed).
6. **2D cesta** označit jako diagnostiku.

Co nedělat: další vyhlazování, další zpoždění, další volby – dokud neproběhne slepý test posunu a měření 3.3.

Stav: uživatel 2026-11-01 rozhodl „hodiny z kitu do her“ (bod 3; zadání odeslána) a schválil kit 0.9.12 = dopočet
objektů o průchod (3.3), pevná zpoždění ve wb-takt (latO 40, adaptace jen s latOMax), cache HUD, centrování úzkých
map, zastarání softClamp/smoothY, testy hodin. Zbývá: přechod režimů (0.9.13), odezva (hráč bez zpoždění, pod
zámkem hned), recept, zmrazení; run-ahead jako experiment po 1.0.

## Příloha A – odpověď Alien Breed II (relace abrii-ab, 2026-11-01)

> „Ostrá“ = mikdenik 313fa79; nasazení a747774 čeká na relaci nasazení. wb-scene je zatím jen ve vývojovém stromu
> (M41, nenasazeno).
> (1) Moduly kitu na stránce: wb-obraz (Presenter WebGL2 s preserve:true kvůli Safari, Screen, CRT a filtry §3 v
> shaderu prezentéru, deviceScale/contentSize, přechod E/O 450 ms smoothstep), wb-nastaveni (menu Obraz/Zvuk), wb-zvuk
> (výstup a filtr LED), wb-seal, wb-touch, wb-datadisk (od M39); nově wb-scene 1.6. wb-takt NEPOUŽÍVÁME – takt je
> vlastní (PACE v main.js). Ani wb-zvuk-worklet / wb-zvuk-out / wb-atn / wb-content – máme vlastní audio-worklet.js,
> arek-atn.js, content.js (starší kopie z doby před moduly).
> Takt (vlastní PACE): AHEAD 2 (replay 1), latC 20 ms vlákno / 30 ms korutina (?latc=; Ladění „kratší“ 10), latO 40 ms
> (?lato=), zamčený takt na k × 50 Hz displeji (latC = FM − 2, latO ≥ 2 FM − 2), jinak hodiny 49,92 Hz a mezipolohy;
> Originál bez plynulosti latC −2 (ukáže hned).
> wb-scene (M41): jen subpixel: true (Ladění, výchozí zapnuto), ostatní volby výchozí (jumpMax 40, passMax 100,
> camMean/softClamp/smoothY/pairOlder/fixedAxis/x17 nenastaveny); takt pro scénu = shim { view: tv/tvO z PACE, pair:
> WBSCENE.pairOf }; hud top/bottom se split [1,96,118,223,255,327], hud.under ne, window.over ne (záznam se shoduje s
> enginem 0 neshod), steady jen u posunutého záblesku.
> Engine: vlákno (COOP/COEP, engine_mt), jinak korutina ASYNCIFY (?mt=0). Zvuk: vlákno = kruh ve sdílené paměti
> (zásoba prefill 20 / cíl 30 / dolní mez 15 ms), korutina = zprávy do workletu (40 / 50 ms).
> (2) Vlastní cesta: view.h view_render (záznamy snímků v kruhu 32, skládání mezipoloh v C: kamera a sprity mezi A/B,
> objekty mezi průchody OA→OB, dopočet dopředu of > 1 až o 1 krok, posun záblesku s hráčem, meze kamery $C117C2,
> záložní obraz pro ne-hru, hires/LACE obrazovky M31, „frz“ = hra stojí a prolíná paletu → snímek originálu v okně) +
> gl.js (terén z atlasu/mřížky na GPU, objekty/sprity jako textury na necelých bodech). Přizpůsobivé latO (60–120 ms
> podle průchodů) existuje, ale s extrapolací enginu je vypnuté (pevně 40); ve wb-scene režimu ho zapínám, protože
> scéna nedopočítává. Pojistka WebGL (2× 5 s s > 5 % pozdních snímků → CPU skládání).
> Ladění (DEV, v publikaci vyříznuto): Kratší zpoždění kamery (vyp.), Objekty a sprity přes WebGL (zap.), Vylepšeno
> přes wb-scene (zap., M41), wb-scene subpixel (zap., M41), takt displeje auto/50 Hz (auto, je v menu Hra), ?gt=0 /
> ?gl=0|1 / ?tr=0 / ?trcrt=0 / ?lat0 / ?lock jen URL.
> (3) Zapojené, ale vypnuté: v Ladění nic z kitu; wb-scene volby vyhlazení (camMean atd.) nenastavené – mezipolohy
> mezi snímky hry stačí, nic jsme pro ABR II neměřili jako potřebné. hud.under – hráč do HUD nezasahuje.
> (4) Zbytečné / duplicitní: dvě celé cesty Vylepšena (view.h+gl.js a wb-scene) – záměrně do rozhodnutí uživatele; po
> přechodu by šlo smazat view_render-mezipolohy, gl.js a VW_SPLIT 1/2 (záložní obrazovky a frz ale zůstanou). Vlastní
> PACE místo wb-takt a vlastní audio-worklet/atn/content místo modulů kitu = duplicita s kitem. latC vs latO: dvojí
> zpoždění má důvod (objekty 25 Hz po průchodech), ale jsou to dvě konstanty + přizpůsobivá logika, která se v
> enginu-extrapolaci vypíná – zmatečné. Cena: záznam sceny ~0,13 ms/snímek hry, HUD se kopíruje do každého záznamu
> (2× ~100 kB); wb-scene _hud rozšiřuje HUD na CPU v každém kreslení.
> (5) Slabá místa mimo KIT-GAPS: Safari E/O problikávání ve WebGL přijaté (uživatel); záblesk u hlavně ve wb-scene
> posouván bez podmínky „nemá pokračování“ (enginová ano) – nový nepřítel do 40 bodů od hráče by se posunul též;
> dotykové zařízení nemá klávesnici pro psaní jména/LEVEL CODE; arek-play má starý build; korutinový engine se
> překládá ~30 min (wasm-opt jedno jádro), vývoj proto zkouší na vlákně a korutina může být „stale“; mapa užší než
> výhled: wb-scene centruje kameru na 0,5 bodu, engine celočíselně (1 sloupec rozdíl, jen úzké mapy).

## Příloha B – odpověď Superfrog (relace sf-sonet-e8, 2026-11-01)

> (1) Ostrá verze: wb-obraz 1.5 (Presenter gl:'auto', CRT), wb-scene 1.6, wb-nastaveni 1.2 (menu Obraz/Zvuk), wb-zvuk
> 1.1 (WBZVUK.chain), wb-datadisk 1.0. wb-takt NEPOUŽÍVÁME: vlastní takt v main.js – rAF povoluje snímky workeru
> (ctl[16]) o krok dopředu (do now + 20 ms, nejvýš 2 před spočítaným), časy v tick[]; modul dostává takt = { view: ts
> => ({ tv: ts − 28, tvO: ts − 48 }), pair: WBSCENE.pairOf } – tedy žádné ahead/latC/latO/lock/extrapolate z wb-takt.
> Scene: camMean {tau:20} (přepínač), pairOlder 2, passMax 100, ring 32, jumpMax výchozí, fixedAxis y v mezihře
> (kamera svisle stojí), subpixel jen Posun A/B; softClamp/smoothY nenastavujeme (odstraněno 1.2), x17 nenastavujeme.
> hud: top {h, rgba, split: []}, under: true. sprites: id = číslo spritu + díl výskytu (k:inst), medailonek screen:
> true; při vypnutých mezipolohách id + '#seq'. window.over = vrstva enginu „zobrazený bod ≠ čisté pozadí bez spritů
> a objektů“ (jen uvnitř původního okna). Engine: WASM ve Web Workeru (ne korutina), balíčky scény v
> SharedArrayBuffer (6 slotů). Zvuk: worker → SAB kruh (48000×2×2 B) → AudioWorklet, zprávou jen inicializace.
> (2) Ladění: Kreslení přes modul kitu (výchozí ZAP; vyp = starší web/scene.js), Svislé vyhlazení kamery (ZAP =
> camMean), Jemné mezipolohy žáby a spritů (ZAP), Nepřátelé a mince v pixelech monitoru (ZAP; v modulu zašedlé –
> modul to dělá vždy), Plynulé barevné přechody/stmívání (ZAP; stránka na dobu kreslení podstrčí prolnutou paletu
> řádků okna), Míchání snímků (VYP, jen bez plynulého zobrazení), Posun A/B (výchozí písmeno bez posunu) + Odhalit.
> Přechod Originál↔Vylepšeno vlastní (web/obraz.js layoutTransition 450 ms, CRT ztlumení na 0,4, vzor bez
> přelaďování) – bez přepínače. CRT z menu Obraz.
> (3) Zapojené/dostupné, nepoužité: wb-takt (rozhodnutí o modulu C nepadlo), wb-seal.js leží ve web/ (bez pečeti,
> rozhodl uživatel), WBSCENE.unexplained() a scene.reset() při pauze zatím ne.
> (4) Duplicitní/zbytečné: dvě kreslení (modul + starší web/scene.js) udržujeme obě a engine kvůli tomu plní všechny
> vrstvy pro oba; zpoždění 28/48 ms je zapsané dvakrát (scene.js LAT/LATO a takt v scena-kit.js); přepínač „v
> pixelech monitoru“ s modulem nic nedělá; Míchání snímků platí jen pro starou cestu; stránka každý snímek přestavuje
> objekty z vrstvy ol (průchod OL_W×OL_H) a kopíruje bob/spr do arény – nejdražší JS na snímek, neměřeno zvlášť.
> (5) Slabá místa mimo KIT-GAPS: vlastní takt bez lock/extrapolace – při zaseknutí hlavního vlákna buffer 25–30 ms
> vyteče (výpadky zvuku, docs/PLYNULOST-K4.md); „mimo seznam“ známe jen v původním okně (v okrajích výřezu chybí;
> podezření u řetězu koule v 5-2, neověřeno); právě opravujeme aktivaci objektů v okrajích výřezu (úvodní blok levelu
> bez levého pásu a 2 spodních řádků → chyběly mince do odchodu a návratu) – chyba v našem rozšíření hry, ne v kitu.
