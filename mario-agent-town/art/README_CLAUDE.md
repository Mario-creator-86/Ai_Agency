# Pachet grafic v2 — instrucțiuni pentru Claude

Mario a cerut explicit ca ChatGPT să DESENEZE orașul și personajele, iar Claude să poată continua implementarea cu imaginile pregătite. Aceasta este livrarea grafică, nu o dovadă că agenții folosesc deja conturi reale.

## Începe aici

1. Folosește branch-ul `mario-agent-town`, folderul `mario-agent-town/` din `Mario-creator-86/Ai_Agency`.
2. Citește `art/manifest.json`, acest fișier, `STYLE_GUIDE.md` și `../HANDOFF.md`.
3. Pornește `npm start` din folderul proiectului, cu Node 24+. Orașul nou este deja integrat în pagina principală. `art-preview.html` prezintă separat ilustrațiile și distribuția.
4. Păstrează această direcție grafică: sat RPG bogat și colorat, grădini și clădiri tematice. NU reveni la casele geometrice pastelate din v1.
5. Continuă întâi integrarea unui singur agent real pe calculatorul Owner. Nu regenera grafica pentru a testa un furnizor.

## Ce imagini există efectiv

| Asset | Fișier | Utilizare |
| --- | --- | --- |
| Hartă completă, fără oameni pictați | `public/assets/village-map-v2.webp` | Fundalul actual al jocului, 1536 × 1024 |
| Zece personaje distincte | `public/assets/characters/<id>.webp` | Fiecare: 768 × 768, grilă 4 × 4, alpha |
| Cadre frontale | `public/assets/portraits/<id>.webp` | Cadru de repaus frontal, pentru portrete/UI |
| Mario confirmat | `public/assets/mario-sprites.webp` | Grilă 4 × 3, pulover cu fermoar scurt la gât |
| 12 clădiri într-un atlas | `public/assets/atlases/buildings-v2.webp` | Case separate pentru viitoare scene/modificări, 4 × 3 |
| Obiecte de decor | `public/assets/atlases/props-v2.webp` | Fântână în 3 cadre, bancă, felinar, copaci, flori, pod, fântână cu acoperiș, panou și jardinieră |
| Distribuția pe o planșă | `public/assets/character-lineup-v2.webp` | Referință rapidă pentru cele 10 identități |

Fișierele PNG originale la rezoluția generată sunt păstrate în pachetul grafic separat pentru Owner. GitHub conține exporturile WebP de lucru. Originalele fotografice ale lui Mario NU sunt incluse. Exporturile WebP păstrează canalul alpha; harta are fundal opac intenționat. Atlasele au și umbre/străluciri semitransparente, care trebuie evaluate pe fundalul efectiv înainte de utilizarea ca obiecte individuale.

## Contractul de animație

Toate cele zece personaje au aceeași ordine a coloanelor:

| Coloană, index de la zero | Direcție |
| --- | --- |
| 0 | Stânga |
| 1 | Dreapta |
| 2 | Față |
| 3 | Spate |

| Rând, index de la zero | Poziție |
| --- | --- |
| 0 | Mers, primul pas |
| 1 | Repaus în picioare |
| 2 | Mers, pasul alternativ |
| 3 | Șezut, fără scaun desenat |

Pentru zece agenți, cadrul are 192 × 192 px în exportul 768 × 768. Mario păstrează sheet-ul 4 × 3 existent, fără rând de șezut. Nu aplica formula cu patru rânduri avatarului CEO. Canvas-ul folosește dimensiunile reale ale imaginii și un pivot la picioare; parametrul curent de desenare este în `public/town.js`. Pentru animare de mers, secvența minimă este rând 0 → 1 → 2 → 1 la 6–8 cadre/s. Imaginile sunt keyframe-uri desenate, nu animație video și nici skeletal rig. Pentru o animație mai fluidă, adaugă cadre între acestea păstrând identitatea.

Unele margini ale sheet-urilor generate pot conține fragmente alpha foarte mici ale cadrului vecin; la un import într-un engine nou, verifică fiecare celulă pe fundal deschis și închis și ajustează dreptunghiul/pivotul per cadru dacă este necesar. Nu redesena chipurile pentru corecții de încadrare.

## Atlasul clădirilor — ordine fixă

Rând 0: Tudor, Ana, Mario, Radu.

Rând 1: Alex, Maria, Town Hall, David.

Rând 2: Irina, Sofia, Elena, Victor.

Atlasul este un set de elemente refolosibile. Harta actuală conține deja clădirile pictate: NU desena atlasul de clădiri peste hartă, altfel le dublezi. Pentru clădiri dinamice sau occlusion corectă, construiește mai târziu un strat de teren separat și așază decupajele deasupra lui. Asta este o etapă ulterioară, nu o funcționalitate pretins implementată aici.

## Coordonate și interacțiune

`public/village-layout.js` este sursa coordonatelor de prezentare. Conține 12 hitbox-uri (zece case, CEO, Town Hall), porțile, etichetele, culoarele și punctele ședinței. Coordonele assetului sunt în pixeli de pe harta 1536 × 1024; funcțiile `worldPoint` / `pixelPoint` le convertesc în lumea 0..20 folosită de API. Vechea poziție x/y din identitățile backend nu determină harta v2 și poate fi eliminată ulterior printr-o schimbare de model atentă.

Personajele și etichetele se desenează pe un strat Canvas separat; ele nu sunt pictate în hartă. A* evită clădirile și bazinul fântânii și ține personajele pe alei/piață. Culoarele sunt aproximări, nu un collision mesh perfect pentru fiecare petală, piatră și zid din pictură. Ședința are loc în piața din fața Town Hall-ului; interioarele caselor NU au fost desenate. Rândul șezut este pregătit pentru utilizare în viitoarele interioare.

Fântâna din fundal are deja o imagine statică. Runtime-ul suprapune stropi și unde decorative. Cele trei cadre din atlas sunt disponibile pentru o viitoare fântână complet separată; nu le dubla peste cea pictată fără a separa întâi stratul de fundal.

## Ce trebuie păstrat

- Exact zece identități și rolurile lor. Numele din manifest corespund ID-urilor backend.
- Mario: cap ras, barbă grizonantă, pulover verde foarte închis CU FERMOAR LA GÂT. Fotografia veche a bărbatului cu păr a fost respinsă explicit.
- Case colorate și diferite după meserie. CEO are cea mai mare reședință.
- Nu confunda o animație de mers cu o execuție AI. „Lucrează” apare numai din starea backend.
- Niciun secret, cont sau fotografie originală în assets ori în Git.

## Ce nu este livrat ca grafică

Nu există interioare pentru toate casele, rigging 3D, sincronizare buze, animații de lucru specifice fiecărei profesii sau un set de terrain tiles fără clădiri. Harta, cele zece sheet-uri și avatarul CEO sunt integrate; atlasul clădirilor și cel de obiecte sunt surse pregătite pentru continuare.
