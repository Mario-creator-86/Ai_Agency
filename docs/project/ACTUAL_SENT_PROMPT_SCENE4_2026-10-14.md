# Prompt efectiv trimis — The Zero Script Club, scena 4

Snapshot cerut de Owner, 14.10.2026. Baza de producție este citită fără scriere.

- Trimitere: 2026-10-14T23:16:47.695894+03:00 (București).
- Model cerut: Qwen-Image-2512; operație imagine, două variante în același lot.
- Prompt: 1963 caractere. Cele două cereri au același prompt: True.
- Referințe în cerere: 0.
- Joburi: 08c98add-8734-4615-bba3-0d8f5b2e107d și 82016154-5f2b-4c32-be5e-811bd2d74f4a.
- La citire: RUNNING; acceptare vizuală: None. Nu există aici dovadă de imagine nouă acceptată.
- Sarah a dat brief v4 cu action rewrite, Kael (mistral-large-4) a rescris, Sarah (deepseek-v4.1-flash) a verificat patru constatări. Dovada aprobării este evenimentul de brief de mai jos; succesul unui apel singur nu constituie aprobare.

## Prompt pozitiv exact, fără scurtare

```text
Warm hand-drawn 2D animation like the studio's own office picture: clean lines, painterly shading, adults at natural proportions with expressive faces. Inside the studio house: wooden desks with glowing monitors, hanging brass lamps in warm amber, bookshelves, potted plants and climbing vines, big windows on the lantern-lit street. Eye-level camera. Vertical 9:16 frame. No written words, letters or logos anywhere. Screens show abstract glow. Location: Accounting & Treasury, ground floor. Medium close-up single at eye level on Nadia, facing the viewer. One continuous picture fills the whole tall frame, the people in its upper two thirds. Pages and screens are blank. In frame, facing the viewer: Nadia: Chestnut hair in a low bun, round tortoiseshell glasses, attentive hazel eyes, wearing plum blouse under a dark violet cardigan, small brass pen on a chain. Nadia seated at her ledger desk facing the viewer, brass pen on its chain resting in her hand over the blank green ledger; Sarah's right shoulder and upper arm only at the right frame edge, her face off camera. Nadia even, with a pause before the number; Sarah measured, checking, her presence held at the frame's edge only. Behind them, quiet ground-floor accounting office: wooden desk, warm brass lamps, bookshelves and plants; two cups of tea cooling on the desk; background life stays soft and does not compete with the foreground action; the green ledger, calculator paper roll and every page are completely blank, unruled and unmarked, with no lines, no writing, no letters. As in the shot before: new location, ground floor; Nadia's ledger desk, brass pen on chain and two cooling tea cups establish the room for scene 5; Sarah's shoulder and upper arm at the right frame edge carry her presence from the penthouse scenes; the camera does not move, zoom or reframe at any point, and Nadia stays centred with Sarah's shoulder and upper arm at the right frame edge from first frame to last.
```

## Prompt negativ exact, fără scurtare

```text
split screen, collage, panels, comic strip, stacked frames, diptych, triptych, grid of pictures, captions, subtitles, logo, watermark, photorealistic live-action footage, glossy 3d cgi render look, chibi or toy proportions, warped or extra hands and fingers, faces or clothes changing between shots, writing on walls, boards or screens, watermarks or logos, on-screen text or captions, plastic or waxy skin, cartoon or 3d-render look when realism is asked for, unmotivated camera movement, clothing, hair or weather changing without reason, faces or bodies morphing mid-shot
```

## Comparație și limită a aprobării

Textul real este identic cu still_prompt curent. Ținuta Nadiei apare complet, fundalul nu mai este întrerupt, Sarah este numită doar ca umăr și braț drept la marginea cadrului, iar cadrul static și păstrarea ei până la final sunt explicite.

Descrierea hainelor vizibile ale lui Sarah lipsește: nu sunt numite sacoul bleumarin sau cămașa albă. in_frame include numai Nadia și reference_images este gol. Aceasta este o omisiune de continuitate față de biblia lui Sarah, chiar dacă verificarea celor patru defecte precedente a declarat toate constatările tratate. Calitatea rezultatului și fidelitatea hainelor se decid din imagine/QC, nu din aprobarea textului. Cererea este nouă, nu reluarea identică a promptului întrerupt de 1.844 de caractere.

Metadata aprobării verificate prin evenimentul care păstrează textul efectiv: {"rewrite_event": 22659, "brief_event": 22664, "review_verdict": "TREATS", "review_run_id": "8e1b0034-7b4d-4576-9d0e-a4f921cd207d", "actual_request_equals_approved_words": true}.

Gate financiar 22668: AGREED. Prompt precedent curent: 1859 caractere; nou: 1963; textele sunt diferite.

## Mișcarea revizuită, pregătită pentru video — încă netrimisă la GPU

```text
Static camera on a fixed tripod, steady, the life of the scene moving inside the fixed frame. Nadia seated at her ledger desk facing the viewer, brass pen on its chain resting in her hand over the blank green ledger; Sarah's right shoulder and upper arm only at the right frame edge, her face off camera. The shot ends on the same medium close-up on Nadia at her desk facing the viewer, brass pen in hand over the blank green ledger, Sarah's shoulder and upper arm still at the right frame edge. Continuous, seamless shot. No subtitles, no on-screen text.
```

Codex nu a apelat modele, nu a pornit/oprit GPU ori serviciul și nu a modificat scene, verdicturi sau politici.
