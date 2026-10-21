# Fiabilitate Ollama și alternativă OpenAI — 19 octombrie 2026

Analiză numai din date existente și documentație publică. Zero apeluri noi de inferență, zero modificări în baza reală, zero schimbări de alocare, bugete sau porniri/reporniri. Instantaneu: 2026-10-19T14:14:33.772464+00:00.

## Diagnosticul verificat

Pentru rescrierile GLM astăzi (de la 00:00 UTC): 72 răspunsuri returnate, 3 apeluri eșuate și 7 răspunsuri goale; 10/82 = 12,2% eșec tehnic. SUCCEEDED nu înseamnă acceptat de Sarah. Din 16 octombrie 12:00 UTC: 137 răspunsuri, 4 FAILED, 7 EMPTY_OUTPUT și 1 ABANDONED; cel abandonat nu este atribuit modelului în rata tehnică (11/148 = 7,43%).

Cele șapte răspunsuri goale au fiecare 65.536 tokeni generați și zero caractere vizibile: total 458.752 tokeni și 61,55 minute în apeluri. Cererile respective au 9.439–10.681 tokeni de intrare; toate rescrierile GLM cu contori disponibili au 7.204–11.013. Catalogul public declară 1M context: datele nu indică epuizarea ferestrei de intrare. Nu se poate exclude sensibilitatea la complexitatea sau contradicțiile instrucțiunilor. Limita efectivă din înregistrări este provider_native, effective_max_tokens=null; nu era un plafon de 3.000 impus accidental aplicației. Memoria și mesajele de direcție sunt 0 caractere în cele șapte cazuri; sistemul are 2.903 caractere și politica Owner 622. Nu este demonstrat un defect de transport/salvare a unui răspuns final existent. [GLM](https://ollama.com/library/glm-5.3-flash).

Separat: șapte rescrieri pe deepseek-v4-flash:cloud au HTTP 410; și vechiul test de conectivitate pe acel nume a avut 410. Aceasta este o eroare de acces la acel identificator, nu o evaluare a calității și nu o depășire de context. Nu le-am inițiat în această analiză. Numele curent al lui Kael este deja deepseek-v4.1-flash; nu pretind că eroarea de nume este încă prezentă. Nu există încă rescrieri scene_prompt_rewrite comparabile pe noua lui alocare în instantaneu.

## Calitatea este distinctă de răspunsul tehnic

Mistral Large 4 a returnat 212/212 răspunsuri, însă subeșantionul legat de reviziile lui Sarah pe contractul vechi v3 are 7 MISSES și 3 TREATS. Aceste zece revizii nu reprezintă toate cele 212 răspunsuri și nu sunt comparabile direct cu v8. Recomandarea anterioară Mistral era provizorie, bazată pe viteză și consum, nu o dovadă de calitate superioară.

GLM are pe subeșantionul revizuit v6 17 TREATS și 3 MISSES; v7 12 TREATS și 1 ACCEPTED_MINOR; v7+again 12 TREATS; v8 șapte TREATS. Lipsa unui verdict nu înseamnă aprobare sau refuz semantic. Cele șapte rezultate v8 revizuite au fost acceptate, iar alte apeluri au eșuat înainte să poată fi revizuite. Nici aprobarea promptului nu garantează că generatorul video respectă instrucțiunea. Nu atribuim automat toate defectele video modelului de text.

## Candidați OpenAI și cost

Pentru rutină structurată: GPT-6 Luna este candidatul economic. Pentru corecțiile dificile ale lui Kael: GPT-6.1 Sol este candidatul cu prioritate pentru evaluare dacă acceptăm costul suplimentar. Alegerea este provizorie: nu avem răspunsuri proprii comparabile OpenAI și nu declarăm un câștigător fără o evaluare pe aceleași cazuri. Nu este necesară mutarea întregii agenții.

Scenariu standard, fără cache: 10.000 tokeni de intrare și 1.000 tokeni de ieșire TOTALI facturați. Prețurile pe milion input/output sunt Luna 0,10/0,50 USD; Sol 2/10 USD. [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

| Model | USD/apel în scenariu | USD/1.000 apeluri identice |
|---|---:|---:|
| GPT-6 Luna | 0,00150 | 1,50 |
| GPT-6.1 Sol | 0,03000 | 30,00 |
| Mistral Large 4 | 0,00889 | 8,89 |
| GLM-5.3 Flash | 0,00200 | 2,00 |
| DeepSeek-v4.1 Flash | 0,00420 | 4,20 |

Tarife Ollama: [pagina oficială](https://ollama.com/pricing). Aceste calcule sunt verificate aritmetic offline. Nu sunt facturi, un benchmark sau costul unui film complet. Exclud cache, credite de abonament, instrumente, revizii suplimentare, reluări, imagini și randări. Dacă cei 1.000 tokeni reprezintă doar textul vizibil și modelul folosește raționament suplimentar, costul crește. OpenAI facturează și raționamentul; poate produce un răspuns incomplet înainte de text vizibil, deci migrarea singură nu elimină riscul. [Raționament și limite](https://developers.openai.com/api/docs/guides/reasoning).

## Soluția propusă, încă neactivată

1. Cerere concentrată pe o scenă: instrucțiuni de reparație de la Sarah, promptul curent, constatările concrete, contractul furnizorului și câmpurile fixe. Eliminarea duplicatelor și contextului fără legătură, păstrând politica Owner, bible și limitările relevante. Nu presupunem că un prompt mai scurt devine automat corect.
2. Schema JSON strictă din aceeași sursă ca validatorul, consum și durată explicite pe încercare, împreună cu verificările de cost. Separarea răspunsului gol, a erorii de schemă, a refuzului de conținut și a HTTP 410. Fără reluarea aceleiași cereri după o eroare permanentă de acces și fără creșteri automate de buget.
3. Revizia lui Sarah și invarianta câmpurilor deja aprobate rămân obligatorii. Contorul celor două randări nu este resetat de rescriere sau schimbarea modelului. Epuizarea bugetului suspendă în mod explicabil; nu este oprită doar de un număr arbitrar de pași.
4. Înainte de OpenAI: adaptorul nostru actual folosește chat/completions și NU aplică extra pentru ramura OpenAI. Deci schimbarea numelui nu ar activa schema strictă sau controlul efortului. Este necesară o integrare verificată, preferabil Responses, cu schema, opțiunile și tratarea incomplete/refusal/usage. Structured Outputs asigură forma, nu adevărul semantic. [Schema oficială](https://developers.openai.com/api/docs/guides/structured-outputs).
5. O evaluare viitoare: aceleași șase cazuri (inclusiv flacăra scenei 6, telescoapele scenei 8, păstrarea still-ului și răspunsuri negative), Luna și Sol, criterii înghețate: JSON valid, toate cerințele lui Sarah tratate, câmpuri fixe identice, timp și cost. Se măsoară costul pe reparație acceptată. Propunere de plafon total 1 USD pentru etapa text, fără randări video; NEAUTORIZATĂ și NEEXECUTATĂ în această analiză. Plafonul trebuie aplicat înainte de apeluri, nu verificat doar după.

Fișiere: output/llm-reliability-2026-10-19/analyze.py și analysis.json. Scriptul citește SQLite mode=ro, query_only și blochează conexiunile prin socket. Verificările lui sunt aritmetice și de consistență a istoricului; nu sunt un test nou al modelelor.

## Comparația cu cei 80 USD declarați de Owner

Instantaneul local are 6262 apeluri Cloud cu ambii contori din 6850 înregistrări, în perioada 2026-09-12T07:36:34.504798+00:00 — 2026-10-19T14:20:54.832063+00:00. Total 213,895,172 tokeni input și 17,975,530 output. Reprețuirea aceluiași volum la tarife standard fără cache, cu suplimentul pentru cele 89 apeluri peste 272.000 input: Luna **35.89 USD**, Sol **717.90 USD**. Nu sunt facturi sau predicții garantate: tokenizarea, consumul de raționament, imaginile de intrare și reluările pot diferi. Înregistrările fără contori nu sunt gratuite prin presupunere. Perioada plăților și creditele efectiv consumate din cei 80 USD nu sunt verificate. Nicio cerere nouă. Dovadă: output/llm-reliability-2026-10-19/owner-80-usd-comparison.json.
