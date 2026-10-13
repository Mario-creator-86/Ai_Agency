[1mdiff --git a/backend/app/media/assembler.py b/backend/app/media/assembler.py[m
[1mindex 10a85be..c56c144 100644[m
[1m--- a/backend/app/media/assembler.py[m
[1m+++ b/backend/app/media/assembler.py[m
[36m@@ -10216,6 +10216,7 @@[m [mdef _clip_plan([m
     a factual film and the composed beat for the serial (`stills_stage._scene_picture`), never[m
     the compiled still prompt that ``visual_prompt`` holds."""[m
     from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us[m
[32m+[m[32m    from app.media.markings import planned_markings  # noqa: PLC0415[m
     from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415[m
     from app.media.still_gate import StillPlan  # noqa: PLC0415[m
 [m
[36m@@ -10225,6 +10226,7 @@[m [mdef _clip_plan([m
     asked = intent.get("camera_move") if isinstance(intent, dict) else None[m
     look = str(package.get("look_block") or "")[m
     words = " ".join(str(package.get("still_prompt") or scene.get("visual_prompt") or "").split())[m
[32m+[m[32m    picture = stills._scene_picture(package, str(scene.get("visual_prompt") or ""), words)[m
     return StillPlan([m
         scene=int(scene["scene_index"]),[m
         still_prompt=words,[m
[36m@@ -10233,12 +10235,15 @@[m [mdef _clip_plan([m
         bible_rules=stills._bible_rules(bible),[m
         look_block=look,[m
         palette_words=stills._palette_words(look),[m
[31m-        scene_picture=stills._scene_picture(package, str(scene.get("visual_prompt") or ""), words),[m
[32m+[m[32m        scene_picture=picture,[m
         narration=" ".join([m
             str(scene.get("voiceover_segment") or scene.get("narration") or "").split()[m
         ),[m
         purpose=str(scene.get("story_purpose") or ""),[m
         must_fix=tuple(must_fix),[m
[32m+[m[32m        # A thermometer's scale is not writing: the look is told, and her look may overturn[m
[32m+[m[32m        # a writing refusal of such a clip (`qc.look_may_overturn`, 2026-10-13).[m
[32m+[m[32m        expected_markings=planned_markings(words, picture),[m
     )[m
 [m
 [m
[36m@@ -10332,6 +10337,7 @@[m [mdef _check_shot([m
             face_counter=face_counter,[m
             judge=judge,[m
             **({"must_fix": plan.must_fix} if plan.must_fix else {}),[m
[32m+[m[32m            **({"expected_markings": plan.expected_markings} if plan.expected_markings else {}),[m
         )[m
 [m
     checked_takes: list[str] = [take_id][m
[1mdiff --git a/backend/app/media/markings.py b/backend/app/media/markings.py[m
[1mnew file mode 100644[m
[1mindex 0000000..aba9ae9[m
[1m--- /dev/null[m
[1m+++ b/backend/app/media/markings.py[m
[36m@@ -0,0 +1,193 @@[m
[32m+[m[32m"""Objects whose own markings are not «text in the picture» (2026-10-13).[m
[32m+[m
[32m+[m[32mThe Owner, on the film «Why the Kelvin Scale Has No 'Zero' to Begin From»: a scene asked for[m
[32m+[m[32ma thermometer, and quality control refused every still for the digits on it. «Nu ai cum să[m
[32m+[m[32mai un termometru fără scris, grade, Celsius.» A thermometer's scale, a gauge's dial, a clock's[m
[32m+[m[32mface and a ruler's graduations ARE the object; the bible's rule against writing is about[m
[32m+[m[32mcaptions, signs, logos and the lettering a model invents.[m
[32m+[m
[32m+[m[32mSo when the scene's plan names such an object (`planned_markings`, read from the still prompt[m
[32m+[m[32mand the scene's written picture — what the picture must show — never from the narration[m
[32m+[m[32malone):[m
[32m+[m
[32m+[m[32m- the vision checks are told the object's markings are expected and asked to count only[m
[32m+[m[32m  writing elsewhere (`picture_qc.judge_still`, `picture_qc.judge_clip`: `markings_note`);[m
[32m+[m[32m- a writing finding is a reading the Director judges like any other — never a hard limit of[m
[32m+[m[32m  the bible that fails closed (`second_look.hard_limits`, `still_gate.may_be_overturned`,[m
[32m+[m[32m  `qc.look_may_overturn`), never anchored serious in her review of a rewrite[m
[32m+[m[32m  (`scene_rewrite.hard_limit`), and her brief is told so (`scene_rewrite._data`);[m
[32m+[m[32m- the still prompt says so instead of «No text» (`still_exclusions`), and a re-roll's positive[m
[32m+[m[32m  words no longer ask for «unmarked objects» (`still_gate.positive_instruction`).[m
[32m+[m
[32m+[m[32mWriting anywhere else, faces and panels change nothing. The list is short and literal — an[m
[32m+[m[32minstrument that cannot exist without its scale, a clock, a keyboard — never a sign, a page, a[m
[32m+[m[32mboard or a screen, which a model fills with gibberish and the bible rightly refuses.[m
[32m+[m[32m"""[m
[32m+[m
[32m+[m[32mfrom __future__ import annotations[m
[32m+[m
[32m+[m[32mimport re[m
[32m+[m[32mfrom collections.abc import Sequence[m
[32m+[m
[32m+[m[32m#: Each object with the spellings that name it: English (the prompts) and the Romanian a[m
[32m+[m[32m#: script's line may use. One key per object; a plan naming it in either language is one.[m
[32m+[m[32mMARKED_OBJECTS: dict[str, str] = {[m
[32m+[m[32m    "thermometer": r"\bthermometers?\b|\btermometr(?:u|e|ul|ele|elor)\b",[m
[32m+[m[32m    "barometer": r"\bbarometers?\b|\bbarometr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "manometer": r"\bmanometers?\b|\bmanometr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "hygrometer": r"\bhygrometers?\b|\bhigrometr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "altimeter": r"\baltimeters?\b|\baltimetr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "speedometer": r"\bspeedometers?\b|\bvitezometr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "odometer": r"\bodometers?\b|\bkilometraj(?:ul|e)?\b",[m
[32m+[m[32m    "tachometer": r"\btachometers?\b|\bturometr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "voltmeter": r"\bvoltmeters?\b|\bvoltmetr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "ammeter": r"\bammeters?\b|\bampermetr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "multimeter": r"\bmultimeters?\b|\bmultimetr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "galvanometer": r"\bgalvanometers?\b|\bgalvanometr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "chronometer": r"\bchronometers?\b|\bcronometr(?:u|e|ul|ele)\b",[m
[32m+[m[32m    "seismograph": r"\bseismographs?\b|\bseismograf(?:ul|e|ele)?\b",[m
[32m+[m[32m    "oscilloscope": r"\boscilloscopes?\b|\bosciloscop(?:ul|e|ele)?\b",[m
[32m+[m[32m    "gauge": r"\bgauges?\b",[m
[32m+[m[32m    "dial": r"\bdials?\b|\bcadran(?:ul|e|ele)?\b",[m
[32m+[m[32m    # Not «six o'clock»: an hour of the day is no clock in the picture.[m
[32m+[m[32m    "clock": r"(?<!o')(?<!o’)\bclocks?\b|\bceas(?:ul|uri|urile)?\b|\bpendul[ăa]\b",[m
[32m+[m[32m    "watch": r"\b(?:wrist|pocket|stop)[- ]?watch(?:es)?\b|\bwatch\s+face\b",[m
[32m+[m[32m    "sundial": r"\bsundials?\b",[m
[32m+[m[32m    "timer": r"\btimers?\b",[m
[32m+[m[32m    "ruler": r"\brulers?\b|\byardsticks?\b|\brigl(?:[ăa]|e|ele)\b",[m
[32m+[m[32m    "tape measure": r"\b(?:tape\s+measures?|measuring\s+tapes?)\b|\brulet[ăa]\b",[m
[32m+[m[32m    "protractor": r"\bprotractors?\b|\braportor(?:ul|e)?\b",[m
[32m+[m[32m    "weighing scale": ([m
[32m+[m[32m        r"\b(?:weighing|kitchen|bathroom|balance|laboratory|lab|spring)\s+scales?\b"[m
[32m+[m[32m        r"|\bcântar(?:ul|e|ele)?\b"[m
[32m+[m[32m    ),[m
[32m+[m[32m    "graduated glass": ([m
[32m+[m[32m        r"\bgraduated\s+(?:cylinders?|beakers?|flasks?|tubes?)\b|\bmeasuring\s+(?:cups?|jugs?)\b"[m
[32m+[m[32m        r"|\bburettes?\b|\bpipettes?\b|\bsyringes?\b|\bcilindr(?:u|ul)\s+gradat\b|\bsering[ăa]\b"[m
[32m+[m[32m    ),[m
[32m+[m[32m    "temperature scale": ([m
[32m+[m[32m        r"\b(?:celsius|fahrenheit|kelvin|centigrade|temperature|graduated|numbered)\s+scales?\b"[m
[32m+[m[32m        r"|\bscal[ăa]\s+(?:celsius|fahrenheit|kelvin|de\s+temperatur[ăa]|gradat[ăa])\b"[m
[32m+[m[32m    ),[m
[32m+[m[32m    "thermostat": r"\bthermostats?\b|\btermostat(?:ul|e|ele)?\b",[m
[32m+[m[32m    "compass": r"\bcompass(?:es)?\b|\bbusol(?:[ăa]|e|ele)\b",[m
[32m+[m[32m    "instrument panel": ([m
[32m+[m[32m        r"\b(?:instrument|control)\s+panels?\b|\bdashboards?\b|\bcockpits?\b"[m
[32m+[m[32m        r"|\bbord(?:ul)?\s+de\s+(?:instrumente|comand[ăa])\b"[m
[32m+[m[32m    ),[m
[32m+[m[32m    "keyboard": ([m
[32m+[m[32m        r"\bkeyboards?\b|\btypewriters?\b|\bkeypads?\b|\bcalculators?\b|\bcash\s+registers?\b"[m
[32m+[m[32m        r"|\btastatur[ăa]\b|\bma[șs]in[ăa]\s+de\s+scris\b"[m
[32m+[m[32m    ),[m
[32m+[m[32m}[m
[32m+[m[32m_PATTERNS: dict[str, re.Pattern[str]] = {[m
[32m+[m[32m    name: re.compile(pattern, re.IGNORECASE) for name, pattern in MARKED_OBJECTS.items()[m
[32m+[m[32m}[m
[32m+[m[32m#: The Owner reads Romanian: the object's name in his sentences (`markings_ro`).[m
[32m+[m[32m_RO: dict[str, str] = {[m
[32m+[m[32m    "thermometer": "termometrul",[m
[32m+[m[32m    "barometer": "barometrul",[m
[32m+[m[32m    "manometer": "manometrul",[m
[32m+[m[32m    "hygrometer": "higrometrul",[m
[32m+[m[32m    "altimeter": "altimetrul",[m
[32m+[m[32m    "speedometer": "vitezometrul",[m
[32m+[m[32m    "odometer": "kilometrajul",[m
[32m+[m[32m    "tachometer": "turometrul",[m
[32m+[m[32m    "voltmeter": "voltmetrul",[m
[32m+[m[32m    "ammeter": "ampermetrul",[m
[32m+[m[32m    "multimeter": "multimetrul",[m
[32m+[m[32m    "galvanometer": "galvanometrul",[m
[32m+[m[32m    "chronometer": "cronometrul",[m
[32m+[m[32m    "seismograph": "seismograful",[m
[32m+[m[32m    "oscilloscope": "osciloscopul",[m
[32m+[m[32m    "gauge": "indicatorul cu cadran",[m
[32m+[m[32m    "dial": "cadranul",[m
[32m+[m[32m    "clock": "ceasul",[m
[32m+[m[32m    "watch": "ceasul de mână",[m
[32m+[m[32m    "sundial": "cadranul solar",[m
[32m+[m[32m    "timer": "cronometrul",[m
[32m+[m[32m    "ruler": "rigla",[m
[32m+[m[32m    "tape measure": "ruleta",[m
[32m+[m[32m    "protractor": "raportorul",[m
[32m+[m[32m    "weighing scale": "cântarul",[m
[32m+[m[32m    "graduated glass": "vasul gradat",[m
[32m+[m[32m    "temperature scale": "scala de temperatură",[m
[32m+[m[32m    "thermostat": "termostatul",[m
[32m+[m[32m    "compass": "busola",[m
[32m+[m[32m    "instrument panel": "bordul de instrumente",[m
[32m+[m[32m    "keyboard": "tastatura",[m
[32m+[m[32m}[m
[32m+[m
[32m+[m
[32m+[m[32mdef planned_markings(*texts: object) -> tuple[str, ...]:[m
[32m+[m[32m    """The objects of `MARKED_OBJECTS` the plan's ``texts`` name, in the order they are first[m
[32m+[m[32m    named, each once; empty when the plan names none. A text that is not a string is read as[m
[32m+[m[32m    its words; None and empty texts say nothing."""[m
[32m+[m[32m    said = " ".join(" ".join(str(text).split()) for text in texts if text)[m
[32m+[m[32m    if not said:[m
[32m+[m[32m        return ()[m
[32m+[m[32m    found: list[tuple[int, str]] = [][m
[32m+[m[32m    for name, pattern in _PATTERNS.items():[m
[32m+[m[32m        match = pattern.search(said)[m
[32m+[m[32m        if match:[m
[32m+[m[32m            found.append((match.start(), name))[m
[32m+[m[32m    names = [name for _at, name in sorted(found)][m
[32m+[m[32m    if "thermometer" in names and "temperature scale" in names:[m
[32m+[m[32m        # A thermometer's Celsius scale is the thermometer's, not a second object.[m
[32m+[m[32m        names.remove("temperature scale")[m
[32m+[m[32m    return tuple(names)[m
[32m+[m
[32m+[m
[32m+[m[32mdef named(names: Sequence[str], article: str = "the") -> str:[m
[32m+[m[32m    """«the thermometer», «the thermometer and the gauge», «a clock, a dial and a gauge»; with[m
[32m+[m[32m    a capital article, only the first («The thermometer and the gauge»)."""[m
[32m+[m[32m    said = [f"{article.lower()} {name}" for name in names][m
[32m+[m[32m    if not said:[m
[32m+[m[32m        return ""[m
[32m+[m[32m    joined = said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1][m
[32m+[m[32m    return joined[:1].upper() + joined[1:] if article[:1].isupper() else joined[m
[32m+[m
[32m+[m
[32m+[m[32mdef markings_note(markings: Sequence[str]) -> str:[m
[32m+[m[32m    """What a model that judges the picture is told when the plan names an object that[m
[32m+[m[32m    carries its own markings (English, for the vision model and the Director); "" when the[m
[32m+[m[32m    plan names none."""[m
[32m+[m[32m    if not markings:[m
[32m+[m[32m        return ""[m
[32m+[m[32m    return ([m
[32m+[m[32m        f"The plan asks for {named(markings, 'a')}: the scale, numbers, units and labels "[m
[32m+[m[32m        "that belong on such an object are part of the object, not writing in the picture, "[m
[32m+[m[32m        "and the picture is right to show them. Count as readable text only writing "[m
[32m+[m[32m        "elsewhere — a caption, a sign, a logo, lettering on nothing, a line that looks like "[m
[32m+[m[32m        "a subtitle — and say in your reason where any writing you see is. Such an object is "[m
[32m+[m[32m        "a photograph of a thing, never a chart, a title or numbers the studio composes "[m
[32m+[m[32m        "itself: its markings are no reason for compose_locally."[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m
[32m+[m[32mdef still_exclusions(markings: Sequence[str]) -> str:[m
[32m+[m[32m    """The still prompt's last sentence: «No text, no logo.» for a scene of plain objects;[m
[32m+[m[32m    for one whose plan names an object that carries its own markings, the object keeps them[m
[32m+[m[32m    (an image model told «no text» leaves a thermometer blank, or draws the digits anyway and[m
[32m+[m[32m    the words were a lie) and only a caption or a logo is kept out."""[m
[32m+[m[32m    if not markings:[m
[32m+[m[32m        return "No text, no logo."[m
[32m+[m[32m    keeps = "keeps its" if len(markings) == 1 else "keep their"[m
[32m+[m[32m    return f"{named(markings, 'The')} {keeps} own scale and markings; no caption, no logo."[m
[32m+[m
[32m+[m
[32m+[m[32mdef markings_kept(markings: Sequence[str]) -> str:[m
[32m+[m[32m    """The same, said positively alone, for a model whose exclusions go to its negative[m
[32m+[m[32m    channel (gen4) and whose prompt says no «no»."""[m
[32m+[m[32m    if not markings:[m
[32m+[m[32m        return ""[m
[32m+[m[32m    keeps = "keeps its" if len(markings) == 1 else "keep their"[m
[32m+[m[32m    return f"{named(markings, 'The')} {keeps} own scale and markings."[m
[32m+[m
[32m+[m
[32m+[m[32mdef markings_ro(markings: Sequence[str]) -> str:[m
[32m+[m[32m    """The objects in the Owner's language: «termometrul», «termometrul și cadranul»."""[m
[32m+[m[32m    names = [_RO.get(name, name) for name in markings][m
[32m+[m[32m    if not names:[m
[32m+[m[32m        return ""[m
[32m+[m[32m    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " și " + names[-1][m
[1mdiff --git a/backend/app/media/picture_qc.py b/backend/app/media/picture_qc.py[m
[1mindex a82cbf2..f400e9f 100644[m
[1m--- a/backend/app/media/picture_qc.py[m
[1m+++ b/backend/app/media/picture_qc.py[m
[36m@@ -91,6 +91,7 @@[m [mfrom app.agents.identity import clipped[m
 from app.agents.vision import frames_at, frames_for, vision_agent[m
 from app.factual.sanitizer import wrap_in_inert_boundary[m
 from app.media.cards import CAPTION_BAND_TOP, FRAME_HEIGHT[m
[32m+[m[32mfrom app.media.markings import markings_note[m
 from app.media.models import ([m
     CharacterBible,[m
     MediaAsset,[m
[36m@@ -2284,9 +2285,15 @@[m [mdef judge_still([m
             "bible_rules": list(plan.bible_rules),[m
         }[m
     )[m
[32m+[m[32m    # An object the plan asks for with its own markings (`markings.planned_markings`,[m
[32m+[m[32m    # 2026-10-13): the look is told its scale is not writing, and asked only about the rest.[m
[32m+[m[32m    marked = tuple(getattr(plan, "expected_markings", ()) or ())[m
[32m+[m[32m    if marked:[m
[32m+[m[32m        shown["planned_markings"] = list(marked)[m
     prompt = ([m
         _STILL_INSTRUCTIONS.format(scene=plan.scene)[m
         + (_FIXES_NOTE if must_fix else "")[m
[32m+[m[32m        + (markings_note(marked) + "\n" if marked else "")[m
         + wrap_in_inert_boundary(json.dumps(shown, ensure_ascii=False)[:8000], "the-still")[m
     )[m
 [m
[36m@@ -2609,6 +2616,11 @@[m [mdef judge_clip([m
         shown["scene_picture"] = getattr(plan, "scene_picture", "") or ""[m
         shown["narration"] = getattr(plan, "narration", "") or ""[m
         shown["must_fix"] = [{"item": number, **item} for number, item in enumerate(must_fix, 1)][m
[32m+[m[32m    # An object the plan asks for with its own markings (`markings.planned_markings`,[m
[32m+[m[32m    # 2026-10-13): the look is told its scale is not writing, in the clip as in the still.[m
[32m+[m[32m    marked = tuple(getattr(plan, "expected_markings", ()) or ())[m
[32m+[m[32m    if marked:[m
[32m+[m[32m        shown["planned_markings"] = list(marked)[m
     prompt = ([m
         _CLIP_INSTRUCTIONS.format([m
             scene=plan.scene,[m
[36m@@ -2616,6 +2628,7 @@[m [mdef judge_clip([m
             studio_note=studio_text_note(studio_text),[m
         )[m
         + (_CLIP_FIXES_NOTE if must_fix else "")[m
[32m+[m[32m        + (markings_note(marked) + "\n" if marked else "")[m
         + wrap_in_inert_boundary(json.dumps(shown, ensure_ascii=False)[:8000], "the-clip")[m
     )[m
 [m
[1mdiff --git a/backend/app/media/prompt_agent.py b/backend/app/media/prompt_agent.py[m
[1mindex 8b1b206..c0dfcc1 100644[m
[1m--- a/backend/app/media/prompt_agent.py[m
[1m+++ b/backend/app/media/prompt_agent.py[m
[36m@@ -55,6 +55,7 @@[m [mfrom app.factual.editorial import SCENE_PURPOSES[m
 from app.factual.models import FactualClaim, ScriptDraft[m
 from app.factual.sanitizer import wrap_in_inert_boundary[m
 from app.media import prompt_lint as lint[m
[32m+[m[32mfrom app.media.markings import markings_kept, planned_markings, still_exclusions[m
 from app.media.models import CharacterBible, Storyboard, StoryboardScene[m
 from app.media.series_look import ([m
     LIGHT_SLOTS,[m
[36m@@ -404,6 +405,11 @@[m [m_SHOTS_INSTRUCTIONS = ([m
     "emotion, at a believable intensity; the background life, which must not compete with the "[m
     "subject; what must match the previous shot (continuity); what the last frame should be "[m
     "left on; the audio intent; the transition into the next shot; and what to avoid.\n\n"[m
[32m+[m[32m    "The still is drawn from the subject, the action, the environment, the camera's framing, "[m
[32m+[m[32m    "the lighting and the composition at the shot's FIRST moment, so those fields describe "[m
[32m+[m[32m    "what is seen then — a pose, a state, a place — never a camera move, a speed or a span of "[m
[32m+[m[32m    "the clip's seconds: those belong only in the camera's move, in motion and in "[m
[32m+[m[32m    "ending_frame.\n\n"[m
     "Show the information rather than narrating it twice: if the narration says a storm grew "[m
     "stronger, the picture shows cloud, wind, water and a reaction, not a caption. Never ask "[m
     "for writing in the picture — no text overlay, title, label, caption or written number: a "[m
[36m@@ -1841,7 +1847,8 @@[m [mdef _still_moment(action: str) -> str:[m
         ][m
         if marks:[m
             part = _then_head(part, min(marks))[m
[31m-        part = _clean_cut(_first_moment(part))[m
[32m+[m[32m        # The camera's path and a tempo are the clip's, never the picture's (2026-10-13).[m
[32m+[m[32m        part = _clean_cut(lint.without_tempo(lint.static_clause(_first_moment(part))))[m
         if part:[m
             kept.append(part)[m
     return "; ".join(kept)[m
[36m@@ -2639,6 +2646,14 @@[m [mdef _clauses_of(text: Any, *, motion: bool = False) -> list[str]:[m
 [m
     def usable(part: str) -> str:[m
         part = without_scene_reference(part)[m
[32m+[m[32m        if not motion:[m
[32m+[m[32m            # A still is one frozen moment (the Owner, 2026-10-13: «în promptul de imagine nu[m
[32m+[m[32m            # are ce să caute indicații de mișcare»): the camera's movement leaves the clause[m
[32m+[m[32m            # (a clause that only moves the camera is the motion's alone), and so do a tempo[m
[32m+[m[32m            # and a span of the clip.[m
[32m+[m[32m            part = lint.without_tempo(lint.static_clause(part))[m
[32m+[m[32m            if not part:[m
[32m+[m[32m                return ""[m
         if ([m
             not re.search(r"[A-Za-z]", part)[m
             or lint.NONE_WORD.match(part)[m
[36m@@ -3135,6 +3150,14 @@[m [mdef compile_prompts([m
             light = f"light {light}"[m
     cast = _cast_sentence(package.get("characters"), faces_banned)[m
     people = _shows_people(" ".join((subject, action, environment, cast)))[m
[32m+[m[32m    # An object that carries its own markings (a thermometer's scale, `markings`): the still[m
[32m+[m[32m    # keeps them and says so instead of «No text» (the Owner, 2026-10-13).[m
[32m+[m[32m    marked = planned_markings([m
[32m+[m[32m        package.get("subject"),[m
[32m+[m[32m        package.get("action"),[m
[32m+[m[32m        package.get("environment"),[m
[32m+[m[32m        package.get("writer_visual"),[m
[32m+[m[32m    )[m
     items = [[m
         (0, 0, block),[m
         (0, 1, frame),[m
[36m@@ -3153,7 +3176,7 @@[m [mdef compile_prompts([m
         # words literally (config/factual_look.json's note; the lint refuses them on veo).[m
         # They stay in the package's `avoid` and reach a model's negative channel where it[m
         # has one (`render_motion`).[m
[31m-        (0, 9, STILL_EXCLUSIONS if still_family != "gen4" else ""),[m
[32m+[m[32m        (0, 9, still_exclusions(marked) if still_family != "gen4" else markings_kept(marked)),[m
     ][m
     still = _fit_sentences(items, lint.prompt_cap(contract, "still"), STILL_MAX_WORDS)[m
     # People kept faceless are shown from behind: an orbit around them turns their faces to[m
[1mdiff --git a/backend/app/media/prompt_lint.py b/backend/app/media/prompt_lint.py[m
[1mindex 049c164..8848e1c 100644[m
[1m--- a/backend/app/media/prompt_lint.py[m
[1m+++ b/backend/app/media/prompt_lint.py[m
[36m@@ -104,6 +104,130 @@[m [mSHOT_SIZE = re.compile([m
     re.IGNORECASE,[m
 )[m
 [m
[32m+[m[32m# A still is one frozen moment: a camera move, a tempo or a span of the clip's seconds is[m
[32m+[m[32m# the motion prompt's and has no place in the picture's words (the Owner, 2026-10-13: «în[m
[32m+[m[32m# promptul de imagine nu are ce să caute indicații de mișcare»). The compiler leaves them out[m
[32m+[m[32m# of the still (`prompt_agent._clauses_of`: a clause that moves the camera is dropped, a tempo[m
[32m+[m[32m# is taken out of its clause) and `lint_still_prompt` says when a stored still prompt still[m
[32m+[m[32m# carries one (STILL_MOTION).[m
[32m+[m[32m#: A tempo or a span of the clip inside a clause: taken out of the still's words.[m
[32m+[m[32mSTILL_TEMPO = re.compile([m
[32m+[m[32m    r"\b(?:slowly|steadily|gradually|gently|smoothly|quickly|rapidly|swiftly|briskly"[m
[32m+[m[32m    r"|continuously|unhurriedly|over\s+the\s+(?:clip|shot)(?:'s)?(?:\s+seconds)?"[m
[32m+[m[32m    r"|throughout\s+the\s+(?:clip|shot)|for\s+the\s+whole\s+(?:clip|shot)"[m
[32m+[m[32m    r"|across\s+the\s+(?:whole\s+)?(?:clip|shot)|over\s+\d+\s+seconds?"[m
[32m+[m[32m    r"|as\s+the\s+(?:clip|shot)\s+(?:goes\s+on|runs|ends)"[m
[32m+[m[32m    r"|by\s+the\s+end\s+of\s+the\s+(?:clip|shot)|from\s+the\s+first\s+frame\s+to\s+the\s+last"[m
[32m+[m[32m    r"|frame\s+by\s+frame|second\s+by\s+second)\b",[m
[32m+[m[32m    re.IGNORECASE,[m
[32m+[m[32m)[m
[32m+[m[32m#: The camera itself as the subject of a verb of movement: the whole clause is the motion's.[m
[32m+[m[32m#: Only the camera, the lens and a drone: «the frame holds only the place and the things[m
[32m+[m[32m#: named» (`prompt_agent.NO_PEOPLE_SENTENCE`) is a composition, and «the shot shows» a[m
[32m+[m[32m#: picture; and only verbs that move it — a camera that «holds» or «stays» is a still.[m
[32m+[m[32mCAMERA_MOVING = re.compile([m
[32m+[m[32m    r"\b(?:the\s+)?(?:camera|lens|drone)\s+"[m
[32m+[m[32m    r"(?:(?:slowly|gently|steadily|smoothly|then)\s+)?"[m
[32m+[m[32m    r"(?:moves?|moving|glides?|gliding|push(?:es|ing)|pulls?|pulling|tracks?|tracking"[m
[32m+[m[32m    r"|follows?|following|circles?|circling|orbits?|orbiting|rises?|rising|descends?"[m
[32m+[m[32m    r"|descending|sweeps?|sweeping|drifts?|drifting|pans?|panning|tilts?|tilting|zooms?"[m
[32m+[m[32m    r"|zooming|cranes?|craning|arcs?|arcing|travels?|travell?ing|swings?|swinging|creeps?"[m
[32m+[m[32m    r"|creeping|floats?|floating|clos(?:es|ing)\s+in|eases?\s+(?:in|out|closer|back)"[m
[32m+[m[32m    r"|easing\s+(?:in|out|closer|back))\b",[m
[32m+[m[32m    re.IGNORECASE,[m
[32m+[m[32m)[m
[32m+[m[32m#: The named moves a still prompt may say without moving anything: a locked camera is a[m
[32m+[m[32m#: composition, a handheld look is grain.[m
[32m+[m[32m_STILL_MAY_NAME = frozenset({"static", "handheld drift"})[m
[32m+[m[32m#: Where a named move is the camera's and not the subject's own: the clause names the camera[m
[32m+[m[32m#: or its stand-ins, or the move is said in the cinema's own words. «Earth orbits the Sun»[m
[32m+[m[32m#: and «she pulls back the curtain» are the subject's moment and stay (the Codex review of[m
[32m+[m[32m#: c6dc05c, 2026-10-13: a bare «orbits» emptied an astronomy scene's still).[m
[32m+[m[32m_CAMERA_CONTEXT = re.compile([m
[32m+[m[32m    r"\b(?:camera|lens|shot|frame|framing|view|viewpoint|drone|pov|point\s+of\s+view)\b",[m
[32m+[m[32m    re.IGNORECASE,[m
[32m+[m[32m)[m
[32m+[m[32m_CAMERA_ONLY_MOVE = re.compile([m
[32m+[m[32m    r"\b(?:doll(?:y|ies|ying)|crane(?:s|ing)?|pedestal|boom(?:s|ing)?\s+(?:up|down)"[m
[32m+[m[32m    r"|track(?:s|ing)?\s+(?:shot\s+)?(?:to\s+the\s+)?(?:left|right)|truck(?:s|ing)?"[m
[32m+[m[32m    r"|pan(?:s|ning)?\s+(?:left|right)|push[- ]in|pull[- ](?:back|out)|aerial\s+drift"[m
[32m+[m[32m    r"|rack[- ]focus|focus\s+(?:racks?|pulls?|pulling)|pull(?:s|ing)?\s+focus|zoom\w*)\b",[m
[32m+[m[32m    re.IGNORECASE,[m
[32m+[m[32m)[m
[32m+[m
[32m+[m
[32m+[m[32mdef _camera_moves_in(text: str) -> list[tuple[int, str]]:[m
[32m+[m[32m    """(start, words) of each named move in ``text`` that is the camera's: not a locked camera[m
[32m+[m[32m    or a handheld look (`_STILL_MAY_NAME`), and either said beside the camera[m
[32m+[m[32m    (`_CAMERA_CONTEXT`) or in the cinema's own words (`_CAMERA_ONLY_MOVE`)."""[m
[32m+[m[32m    lowered = text.lower()[m
[32m+[m[32m    beside_the_camera = bool(_CAMERA_CONTEXT.search(text))[m
[32m+[m[32m    found: list[tuple[int, str]] = [][m
[32m+[m[32m    for move, written in camera_moves(text):[m
[32m+[m[32m        if move in _STILL_MAY_NAME:[m
[32m+[m[32m            continue[m
[32m+[m[32m        if not beside_the_camera and not _CAMERA_ONLY_MOVE.search(written):[m
[32m+[m[32m            continue[m
[32m+[m[32m        at = lowered.find(written.lower())[m
[32m+[m[32m        if at >= 0:[m
[32m+[m[32m            found.append((at, written))[m
[32m+[m[32m    return found[m
[32m+[m
[32m+[m
[32m+[m[32mdef still_motion(text: str) -> str:[m
[32m+[m[32m    """The earliest words of a still prompt that move the camera (a named move of the camera,[m
[32m+[m[32m    or the camera as the subject of a verb of movement) or give a tempo or a span of the[m
[32m+[m[32m    clip, else ""."""[m
[32m+[m[32m    found: list[tuple[int, str]] = [][m
[32m+[m[32m    for pattern in (CAMERA_MOVING, STILL_TEMPO):[m
[32m+[m[32m        match = pattern.search(text)[m
[32m+[m[32m        if match:[m
[32m+[m[32m            found.append((match.start(), match.group(0).strip()))[m
[32m+[m[32m    found += _camera_moves_in(text)[m
[32m+[m[32m    return min(found)[1] if found else ""[m
[32m+[m
[32m+[m
[32m+[m[32mdef moves_the_camera(text: str) -> bool:[m
[32m+[m[32m    """Whether a clause of a plan field moves the camera (`CAMERA_MOVING`, or a named move[m
[32m+[m[32m    that is the camera's, `_camera_moves_in`)."""[m
[32m+[m[32m    return bool(CAMERA_MOVING.search(text)) or bool(_camera_moves_in(text))[m
[32m+[m
[32m+[m
[32m+[m[32m#: What joins a subject's moment to the camera's move in one clause ("the mercury rises as[m
[32m+[m[32m#: the camera pushes in"): cut off with the move, the moment stays.[m
[32m+[m[32m_BEFORE_CAMERA = re.compile(r"\s*(?:,|;|\b(?:as|while|and|with|then|before|until)\b)\s*$")[m
[32m+[m
[32m+[m
[32m+[m[32mdef static_clause(text: str) -> str:[m
[32m+[m[32m    """A clause of a plan field as a still may say it: without the camera's movement. A clause[m
[32m+[m[32m    that only moves the camera is "" (the motion prompt's); one that says a moment first[m
[32m+[m[32m    ("the mercury rises as the camera pushes in on the scale") keeps the moment ("the mercury[m
[32m+[m[32m    rises") when at least two words of it stay whole."""[m
[32m+[m[32m    starts = [match.start() for match in CAMERA_MOVING.finditer(text)][m
[32m+[m[32m    starts += [at for at, _written in _camera_moves_in(text)][m
[32m+[m[32m    if not starts:[m
[32m+[m[32m        return text[m
[32m+[m[32m    first = min(starts)[m
[32m+[m[32m    head = _BEFORE_CAMERA.sub("", text[:first]).strip()[m
[32m+[m[32m    # The move was named by a subject of its own ("the camera"): the head ends before it.[m
[32m+[m[32m    head = re.sub(r"\s*\b(?:the|a|an)\s*$", "", head, flags=re.IGNORECASE).strip(" ,;")[m
[32m+[m[32m    if len(head.split()) < 2 or dangling(head):[m
[32m+[m[32m        return ""[m
[32m+[m[32m    # A head that is only the camera's own name ("the view", "the camera") says no picture.[m
[32m+[m[32m    if _CAMERA_CONTEXT.fullmatch(re.sub(r"^(?:the|a|an)\s+", "", head, flags=re.IGNORECASE)):[m
[32m+[m[32m        return ""[m
[32m+[m[32m    return head[m
[32m+[m
[32m+[m
[32m+[m[32mdef without_tempo(text: str) -> str:[m
[32m+[m[32m    """``text`` with its tempo and clip-span words taken out (`STILL_TEMPO`), the spacing and[m
[32m+[m[32m    the punctuation closed up: "cloud rolls steadily across the ridges" is "cloud rolls across[m
[32m+[m[32m    the ridges"."""[m
[32m+[m[32m    said = STILL_TEMPO.sub(" ", text)[m
[32m+[m[32m    said = re.sub(r"\s+([,;.!?])", r"\1", re.sub(r"\s{2,}", " ", said))[m
[32m+[m[32m    return said.strip()[m
[32m+[m
[32m+[m
 # The tempo a motion prompt must say once. "Smooth", "fluid", "deliberate" and "sweeping"[m
 # are the cinema's tempo words for an ample move (2026-10-11); "fast" and "quick" stay for a[m
 # plan that asks for them (production_policy reads "fast" as a fast-motion need).[m
[36m@@ -863,6 +987,21 @@[m [mdef lint_still_prompt([m
                 "într-unul; descrieți locul în cuvinte.",[m
             )[m
         )[m
[32m+[m[32m    # WARN, as STILL_SEQUENCE: the compiler keeps movement out of the still (2026-10-13); this[m
[32m+[m[32m    # tells the Owner when a stored prompt still carries a camera move, a tempo or a span.[m
[32m+[m[32m    moving = still_motion(text)[m
[32m+[m[32m    if moving:[m
[32m+[m[32m        findings.append([m
[32m+[m[32m            _finding([m
[32m+[m[32m                "STILL_MOTION",[m
[32m+[m[32m                WARN,[m
[32m+[m[32m                scene,[m
[32m+[m[32m                moving,[m
[32m+[m[32m                f"Promptul imaginii cere mișcare („{moving}”). O imagine este un singur moment "[m
[32m+[m[32m                "nemișcat: mișcarea camerei, tempoul și durata clipului se spun doar în "[m
[32m+[m[32m                "promptul de mișcare. Descrieți ce se vede în acel moment.",[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
 [m
     rule = bible_face_rule(bible)[m
     if rule:[m
[1mdiff --git a/backend/app/media/qc.py b/backend/app/media/qc.py[m
[1mindex 7041ceb..0a88657 100644[m
[1m--- a/backend/app/media/qc.py[m
[1m+++ b/backend/app/media/qc.py[m
[36m@@ -48,6 +48,7 @@[m [mfrom app.db import lock_for_write[m
 from app.factual.editorial import dangles[m
 from app.factual.models import FactualClaim[m
 from app.media.cards import film_finish[m
[32m+[m[32mfrom app.media.markings import planned_markings[m
 from app.media.models import ([m
     MediaAsset,[m
     QualityControlReport,[m
[36m@@ -2219,9 +2220,14 @@[m [mdef check_clip([m
     judge: Callable[[list[Path]], Any] | None = None,[m
     work_dir: Path | None = None,[m
     must_fix: Sequence[Mapping[str, Any]] = (),[m
[32m+[m[32m    expected_markings: Sequence[str] = (),[m
 ) -> ClipReport:[m
     """Measure one bought clip before it is cut into the film, at 0 credits.[m
 [m
[32m+[m[32m    ``expected_markings`` (2026-10-13): the plan's objects that carry their own markings[m
[32m+[m[32m    (`still_gate.StillPlan.expected_markings`), kept on ``measured["picture"]`` so that a[m
[32m+[m[32m    writing refusal of such a clip is the Director's to overturn (`look_may_overturn`).[m
[32m+[m
     - motion: mean YDIF at 540 px against the floor of its camera move (`motion_check`);[m
     - cuts: a hard cut inside the clip fails it (`cut_spikes`);[m
     - faces: YuNet on the first, middle and last frames when the bible forbids faces;[m
[36m@@ -2307,6 +2313,8 @@[m [mdef check_clip([m
             }[m
             if fixes:[m
                 measured["picture"]["fixes"] = fixes[m
[32m+[m[32m            if expected_markings:[m
[32m+[m[32m                measured["picture"]["planned_markings"] = [str(n) for n in expected_markings][m
     finally:[m
         if owned:[m
             shutil.rmtree(folder, ignore_errors=True)[m
[36m@@ -2642,7 +2650,11 @@[m [mdef look_may_overturn(report: ClipReport) -> bool:[m
     picture = (report.measured or {}).get("picture") or {}[m
     flags = picture.get("verdict") if isinstance(picture, dict) else None[m
     flags = flags if isinstance(flags, dict) else {}[m
[31m-    if flags.get("readable_text") or flags.get("one_picture") is False:[m
[32m+[m[32m    if flags.get("one_picture") is False:[m
[32m+[m[32m        return False[m
[32m+[m[32m    # Writing on a clip whose plan asks for an object with its own markings (a thermometer's[m
[32m+[m[32m    # scale, ``planned_markings``) is a reading, hers to judge (2026-10-13).[m
[32m+[m[32m    if flags.get("readable_text") and not picture.get("planned_markings"):[m
         return False[m
     faces = next((item for item in report.checks if item.code == "faces"), None)[m
     forbidden = faces is not None and faces.status != "NOT_APPLICABLE"[m
[36m@@ -3756,6 +3768,9 @@[m [mdef span_picture_qc([m
                         faces_forbidden=faces_forbidden,[m
                         bible_rules=rules,[m
                         look_block=str(asked.get("look_block") or ""),[m
[32m+[m[32m                        # A thermometer's scale is not writing (2026-10-13): the look is[m
[32m+[m[32m                        # told, and her second look at the scene may overturn the reading.[m
[32m+[m[32m                        expected_markings=planned_markings(asked.get("still_prompt")),[m
                     )[m
                     judgement = judge([path for _at, _moment, path in looked_at], plan)[m
                 picture = _picture_check(judgement, faces_forbidden=faces_forbidden)[m
[1mdiff --git a/backend/app/media/scene_rewrite.py b/backend/app/media/scene_rewrite.py[m
[1mindex 84c516a..736e80a 100644[m
[1m--- a/backend/app/media/scene_rewrite.py[m
[1m+++ b/backend/app/media/scene_rewrite.py[m
[36m@@ -7,6 +7,7 @@[m [mfrom __future__ import annotations[m
 import json[m
 import logging[m
 import re[m
[32m+[m[32mfrom collections.abc import Sequence[m
 from typing import Any, Literal[m
 from uuid import uuid4[m
 [m
[36m@@ -19,6 +20,7 @@[m [mfrom app.db import lock_for_write[m
 from app.factual.models import ScriptDraft[m
 from app.factual.sanitizer import wrap_in_inert_boundary[m
 from app.media import prompt_lint as lint[m
[32m+[m[32mfrom app.media.markings import markings_kept, markings_note, planned_markings, still_exclusions[m
 from app.media.models import SceneTake, Storyboard, StoryboardScene[m
 from app.models import DomainEvent[m
 from app.services import append_event[m
[36m@@ -149,6 +151,18 @@[m [mHARD_LIMIT_WORDS = re.compile([m
     r"faces? (?:are |is )?forbidden",[m
     re.IGNORECASE,[m
 )[m
[32m+[m[32m#: The same words, split: writing alone is no hard limit when the plan names an object that[m
[32m+[m[32m#: carries its own markings (`markings.planned_markings`; the Owner, 2026-10-13, the Kelvin[m
[32m+[m[32m#: film's thermometer refused for the digits of its scale), the rest always is.[m
[32m+[m[32m_WRITING_LIMIT = re.compile([m
[32m+[m[32m    r"text lizibil|apare text|readable text|garbled text|lettering", re.IGNORECASE[m
[32m+[m[32m)[m
[32m+[m[32m_OTHER_LIMITS = re.compile([m
[32m+[m[32m    r"interzice fețele|panour\w*|colaj|ecran împărțit|bandă goală|\bpanels?\b|collage|"[m
[32m+[m[32m    r"split[- ]screen|o singură fotografie|încalcă biblia|breaks the bible|"[m
[32m+[m[32m    r"faces? (?:are |is )?forbidden",[m
[32m+[m[32m    re.IGNORECASE,[m
[32m+[m[32m)[m
 #: A face named in quality control's words: a hard limit when the bible forbids faces. Only[m
 #: the Romanian «chip» with its endings: a bare «chip» is the English word (a microchip film).[m
 _FACE_WORDS = re.compile([m
[36m@@ -771,7 +785,11 @@[m [m_REWRITE_INSTRUCTIONS = ([m
     "in the picture. Do not add facts, numbers, dates or events that are not in the narration. "[m
     "Give the shot one ample, specific camera move with its path and tempo (where it starts, "[m
     "where it ends over the clip's seconds) and write what the subject does as verbs; choose "[m
[31m-    "camera_move from: {moves}. Name colours in words. Return only JSON with this shot: "[m
[32m+[m[32m    "camera_move from: {moves}. Name colours in words. The picture's fields (subject, action, "[m
[32m+[m[32m    "environment, camera, lighting, composition) describe one frozen moment — what is seen, a "[m
[32m+[m[32m    "pose, a state, a place — with no camera move, no speed and no span of the clip in them: "[m
[32m+[m[32m    "a still cannot show movement, so everything that moves goes to motion, camera_move and "[m
[32m+[m[32m    "ending_frame only. Return only JSON with this shot: "[m
     '{{"scene_index": {scene}, "subject": "...", "action": "...", "environment": "...", '[m
     '"camera": "...", "camera_move": "...", "lighting": "...", "composition": "...", '[m
     '"motion": "...", "emotion": "...", "background": "...", "continuity": "...", '[m
[36m@@ -1183,6 +1201,15 @@[m [mdef scene_context(engine: Engine, storyboard_id: str, scene_index: int) -> dict[[m
                 _brief_in_short(brief) for brief in briefs[:-MAX_BRIEFS_SHOWN][-MAX_OLDER_BRIEFS:][m
             ],[m
             "last_code": last_code,[m
[32m+[m[32m            # The plan's objects that carry their own markings (`markings.planned_markings`):[m
[32m+[m[32m            # a writing finding about them is hers to rate, never anchored serious.[m
[32m+[m[32m            "markings": planned_markings([m
[32m+[m[32m                package.get("still_prompt") or target.visual_prompt,[m
[32m+[m[32m                package.get("writer_visual"),[m
[32m+[m[32m                package.get("subject"),[m
[32m+[m[32m                package.get("action"),[m
[32m+[m[32m                package.get("environment"),[m
[32m+[m[32m            ),[m
             "layers": open_layers(session, storyboard_id, scene_index, last_code=last_code),[m
             "local_move": _local_move(session, storyboard_id, scene_index),[m
         }[m
[36m@@ -1297,10 +1324,14 @@[m [mdef _still_sentences([m
             if sentence.startswith("In frame, facing the viewer:")[m
         ][m
         return found, {}[m
[32m+[m[32m    # The exclusions as this scene says them: «No text, no logo.», or the object's own scale[m
[32m+[m[32m    # kept when the plan names one that carries markings (`markings`, 2026-10-13).[m
[32m+[m[32m    marked = tuple(context.get("markings") or ())[m
     candidates = [[m
         str(package.get("look_block") or ""),[m
         words.COMPOSITION_SENTENCE,[m
[31m-        words.STILL_EXCLUSIONS,[m
[32m+[m[32m        still_exclusions(marked),[m
[32m+[m[32m        markings_kept(marked),[m
     ][m
     people = _present([words.PEOPLE_SENTENCE, words.NO_PEOPLE_SENTENCE], still)[m
     return _present(candidates, still), ({"subject": people} if people else {})[m
[36m@@ -1519,9 +1550,29 @@[m [mdef _data(context: dict[str, Any], **more: Any) -> dict[str, Any]:[m
         data["older_briefs_in_short"] = list(context["older_briefs"])[m
     if context.get("serial"):[m
         data["serial_shot"] = _serial_shot(context)[m
[32m+[m[32m    if context.get("markings"):[m
[32m+[m[32m        # The plan's objects that carry their own markings (`_markings_note`).[m
[32m+[m[32m        data["planned_markings"] = list(context["markings"])[m
     return data[m
 [m
 [m
[32m+[m[32mdef _markings_note(context: dict[str, Any]) -> str:[m
[32m+[m[32m    """Added to her brief and her review when the plan names an object that carries its own[m
[32m+[m[32m    markings (`markings.planned_markings`; the Owner, 2026-10-13, the Kelvin film's thermometer[m
[32m+[m[32m    refused for its digits): its scale is the object, not writing in the picture, and no[m
[32m+[m[32m    rewrite is asked to take it away."""[m
[32m+[m[32m    marked = tuple(context.get("markings") or ())[m
[32m+[m[32m    if not marked:[m
[32m+[m[32m        return ""[m
[32m+[m[32m    return ([m
[32m+[m[32m        markings_note(marked)[m
[32m+[m[32m        + " A finding that reads such markings as text in the picture is a misreading, "[m
[32m+[m[32m        "treated by nothing he writes: rate it minor, never brief him to remove the object's "[m
[32m+[m[32m        "scale or to leave the object blank; only writing elsewhere is a defect of the "[m
[32m+[m[32m        "words.\n"[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m
 def _dumps(data: Any) -> str:[m
     return json.dumps(data, ensure_ascii=False, default=str)[m
 [m
[36m@@ -1672,6 +1723,7 @@[m [mdef director_brief([m
             layers=str(context.get("layers_note") or _LAYERS_OPEN.get(layers, "")),[m
         )[m
         + (_SERIAL_BRIEF_NOTE if context.get("serial") else "")[m
[32m+[m[32m        + _markings_note(context)[m
         + lessons_rule(lessons)[m
         + wrap_in_inert_boundary(_fitted(_data(context, **more), lessons), "scene-brief")[m
     )[m
[36m@@ -1889,13 +1941,18 @@[m [mdef _is_finding(text: str) -> bool:[m
     return not any(pattern.search(_norm(text)) for pattern in notes)[m
 [m
 [m
[31m-def hard_limit(text: Any, bible: dict[str, Any] | None) -> bool:[m
[32m+[m[32mdef hard_limit(text: Any, bible: dict[str, Any] | None, markings: Sequence[str] = ()) -> bool:[m
     """Whether quality control's words name what the bible's hard limits forbid[m
     (`HARD_LIMIT_WORDS`; a face, when the bible forbids faces): such a finding is serious[m
[31m-    whatever a review says (2026-10-12 evening review of a50407e)."""[m
[32m+[m[32m    whatever a review says (2026-10-12 evening review of a50407e). Writing alone is not one[m
[32m+[m[32m    when the plan names an object that carries its own markings (``markings``,[m
[32m+[m[32m    `markings.planned_markings`): a thermometer's scale is the object, and her review rates[m
[32m+[m[32m    the finding (the Owner, 2026-10-13)."""[m
     said = _norm(text)[m
[31m-    if HARD_LIMIT_WORDS.search(said):[m
[32m+[m[32m    if _OTHER_LIMITS.search(said):[m
         return True[m
[32m+[m[32m    if _WRITING_LIMIT.search(said):[m
[32m+[m[32m        return not markings[m
     return bool(lint.bible_face_rule(bible or {})) and bool(_FACE_WORDS.search(said))[m
 [m
 [m
[36m@@ -2017,6 +2074,9 @@[m [mdef review_rewrite([m
     }[m
     if context.get("serial"):[m
         data["serial_shot"] = _serial_shot(context)[m
[32m+[m[32m    if context.get("markings"):[m
[32m+[m[32m        # The plan's objects that carry their own markings (`_markings_note`).[m
[32m+[m[32m        data["planned_markings"] = list(context["markings"])[m
     if earlier:[m
         data["your_earlier_review"] = {[m
             "verdict": earlier.get("verdict"),[m
[36m@@ -2032,14 +2092,20 @@[m [mdef review_rewrite([m
             lesson_chars=LESSON_CHARS_ASKED,[m
         )[m
         + (_SECOND_REVIEW_NOTE if earlier else "")[m
[32m+[m[32m        + _markings_note(context)[m
         + lessons_rule(lessons)[m
         + (_REVIEW_LESSONS_NOTE if lessons else "")[m
         + wrap_in_inert_boundary(_fitted(data, lessons), "rewrite-review")[m
     )[m
     editable = tuple(terms["fields_he_may_change"])[m
     # Serious whatever she says: the bible's hard limits, and what her earlier review in this[m
[31m-    # rung found serious (2026-10-12 evening review of a50407e).[m
[31m-    serious = {int(item["id"]) for item in qc if hard_limit(item.get("qc_text"), context["bible"])}[m
[32m+[m[32m    # rung found serious (2026-10-12 evening review of a50407e). Writing on an object the plan[m
[32m+[m[32m    # asks for with its own markings is not one (2026-10-13).[m
[32m+[m[32m    serious = {[m
[32m+[m[32m        int(item["id"])[m
[32m+[m[32m        for item in qc[m
[32m+[m[32m        if hard_limit(item.get("qc_text"), context["bible"], context.get("markings") or ())[m
[32m+[m[32m    }[m
     serious |= {[m
         int(item.get("id") or 0)[m
         for item in (earlier or {}).get("findings") or [][m
[1mdiff --git a/backend/app/media/second_look.py b/backend/app/media/second_look.py[m
[1mindex b1558b1..7a99167 100644[m
[1m--- a/backend/app/media/second_look.py[m
[1m+++ b/backend/app/media/second_look.py[m
[36m@@ -76,6 +76,7 @@[m [mfrom sqlalchemy.orm import Session[m
 [m
 from app.agents.identity import clipped[m
 from app.factual.sanitizer import wrap_in_inert_boundary[m
[32m+[m[32mfrom app.media.markings import markings_note, planned_markings[m
 from app.media.models import ([m
     MediaAsset,[m
     SceneTake,[m
[36m@@ -170,17 +171,21 @@[m [m_HARD_RO = {[m
 }[m
 [m
 [m
[31m-def hard_limits(refusal: Iterable[Any], *, faces_forbidden: bool) -> list[str]:[m
[32m+[m[32mdef hard_limits([m
[32m+[m[32m    refusal: Iterable[Any], *, faces_forbidden: bool, markings: Sequence[str] = ()[m
[32m+[m[32m) -> list[str]:[m
     """Which of the bible's hard limits quality control's words read («faces» only where the[m
     bible forbids faces; «panels» for panels, a collage or a flat band; «writing» for readable[m
[31m-    or garbled writing), in that order; empty when none."""[m
[32m+[m[32m    or garbled writing — unless the plan names an object that carries its own markings,[m
[32m+[m[32m    ``markings``, when the writing is hers to judge: a thermometer's scale is the object, the[m
[32m+[m[32m    Owner, 2026-10-13), in that order; empty when none."""[m
     text = _NEGATED.sub(" ", " ".join(" ".join(str(part or "").split()) for part in refusal))[m
     found: list[str] = [][m
     if faces_forbidden and _FACE_WORDS.search(text):[m
         found.append("faces")[m
     if _PANEL_WORDS.search(text):[m
         found.append("panels")[m
[31m-    if _WRITING_WORDS.search(text):[m
[32m+[m[32m    if _WRITING_WORDS.search(text) and not markings:[m
         found.append("writing")[m
     return found[m
 [m
[36m@@ -420,7 +425,13 @@[m [m_SUMMARY_RO = {[m
 [m
 [m
 def _instructions([m
[31m-    kind: str, scene: int, title: str, layout: str, writing: str, hard_rule: str | None[m
[32m+[m[32m    kind: str,[m
[32m+[m[32m    scene: int,[m
[32m+[m[32m    title: str,[m
[32m+[m[32m    layout: str,[m
[32m+[m[32m    writing: str,[m
[32m+[m[32m    hard_rule: str | None,[m
[32m+[m[32m    markings: Sequence[str] = (),[m
 ) -> str:[m
     lines = [[m
         f"You are the Director. Quality control refused {_WHAT[kind]} of scene {scene} of the "[m
[36m@@ -461,6 +472,14 @@[m [mdef _instructions([m
             "the picture at all (quality control misread it); if any of it is there, CONFIRMED, "[m
             "severity serious, redo true."[m
         )[m
[32m+[m[32m    if markings:[m
[32m+[m[32m        # The Owner, 2026-10-13: «Nu ai cum să ai un termometru fără scris, grade, Celsius.»[m
[32m+[m[32m        lines.append([m
[32m+[m[32m            markings_note(markings) + " Writing that is only such an object's own scale is no "[m
[32m+[m[32m            "defect: say OVERTURNED with severity none when that is all the writing you see, "[m
[32m+[m[32m            "minor when a small trace of other writing is there, and CONFIRMED only for writing "[m
[32m+[m[32m            "elsewhere that draws the eye."[m
[32m+[m[32m        )[m
     lines += [[m
         "- cause (required with minor or serious): one sentence, why the defect appears — what "[m
         "in the prompt, the plan, the still or the model made it. The Owner: understand why "[m
[36m@@ -664,6 +683,11 @@[m [mdef scene_intent([m
         "camera_move": package.get("camera_move") or None,[m
         "look": _short(package.get("look_block"), 400) or None,[m
     }[m
[32m+[m[32m    # The plan's objects that carry their own markings (`markings.planned_markings`): writing[m
[32m+[m[32m    # on them is hers to judge, never a hard limit (2026-10-13).[m
[32m+[m[32m    marked = planned_markings(still_prompt, writer)[m
[32m+[m[32m    if marked:[m
[32m+[m[32m        intent["plan"]["planned_markings"] = list(marked)[m
     if bought:[m
         _plan_as_bought(session, storyboard_id, scene_index, bought, intent["plan"])[m
     avoid = bible.get("avoid")[m
[36m@@ -1437,6 +1461,13 @@[m [mdef _record([m
                     "layer": outcome.get("layer"),[m
                     "source": outcome.get("source"),[m
                     "hard_limits": list(context.get("hard_limits") or []),[m
[32m+[m[32m                    # Only when the plan names an object with its own markings (2026-10-13):[m
[32m+[m[32m                    # the event of a plain scene reads as it always did.[m
[32m+[m[32m                    **([m
[32m+[m[32m                        {"planned_markings": list(context["planned_markings"])}[m
[32m+[m[32m                        if context.get("planned_markings")[m
[32m+[m[32m                        else {}[m
[32m+[m[32m                    ),[m
                     "fail_closed": bool(context.get("fail_closed")),[m
                     "plan_as_bought": list(context.get("plan_as_bought") or []),[m
                     "plan_may_be_newer": bool(context.get("plan_may_be_newer")),[m
[36m@@ -1644,13 +1675,17 @@[m [mdef _look([m
         said_plan, said_bible = intent.get("plan"), intent.get("bible")[m
         plan: dict[str, Any] = said_plan if isinstance(said_plan, dict) else {}[m
         bible: dict[str, Any] = said_bible if isinstance(said_bible, dict) else {}[m
[31m-        limits = hard_limits(refusal, faces_forbidden=bool(bible.get("faces_forbidden")))[m
[32m+[m[32m        marked = tuple(str(name) for name in plan.get("planned_markings") or [])[m
[32m+[m[32m        limits = hard_limits([m
[32m+[m[32m            refusal, faces_forbidden=bool(bible.get("faces_forbidden")), markings=marked[m
[32m+[m[32m        )[m
         context.update([m
             title=title,[m
             serial=intent.get("serial") if "serial" in intent else None,[m
             plan_as_bought=list(plan.get("as_bought") or []),[m
             plan_may_be_newer=bool(plan.get("plan_may_be_newer")),[m
             hard_limits=limits,[m
[32m+[m[32m            planned_markings=list(marked),[m
         )[m
         director = agent_for_role(session, "Director")[m
         if director is None:[m
[36m@@ -1682,10 +1717,12 @@[m [mdef _look([m
     }[m
     if limits:[m
         shown["hard_limits"] = limits[m
[32m+[m[32m    if marked:[m
[32m+[m[32m        shown["planned_markings"] = list(marked)[m
     layout = str((view or {}).get("layout") or _LAYOUT[kind])[m
     writing = str((view or {}).get("writing") or _WRITING[kind])[m
     prompt = _instructions([m
[31m-        kind, scene_index, title[:80], layout, writing, rule[m
[32m+[m[32m        kind, scene_index, title[:80], layout, writing, rule, marked[m
     ) + wrap_in_inert_boundary(_fit_shown(shown), "second-look")[m
     try:[m
         parsed, first, second = structured_run([m
[1mdiff --git a/backend/app/media/still_gate.py b/backend/app/media/still_gate.py[m
[1mindex 3ed226c..c278f82 100644[m
[1m--- a/backend/app/media/still_gate.py[m
[1m+++ b/backend/app/media/still_gate.py[m
[36m@@ -176,6 +176,7 @@[m [mfrom app.media.fix_check import ([m
     fix_status,[m
     minor_traces,[m
 )[m
[32m+[m[32mfrom app.media.markings import markings_ro, named[m
 from app.media.picture_qc import StillJudgement, judge_still[m
 from app.media.qc import PANEL_BAND_SHARE, flat_band, still_is_degenerate[m
 from app.media.toolchain import find_ffmpeg[m
[36m@@ -331,6 +332,11 @@[m [mclass StillPlan:[m
     #: persists is refused (`decide`, ``finding_persists``). Clip QC reads the motion layer's[m
     #: items from the same field of its own plan (`assembler._clip_plan`).[m
     must_fix: tuple[dict[str, Any], ...] = ()[m
[32m+[m[32m    #: The objects the plan names that carry their own markings (`markings.planned_markings`;[m
[32m+[m[32m    #: the Owner, 2026-10-13, the Kelvin film's thermometer refused for its digits): the look[m
[32m+[m[32m    #: is told their scale is not writing, and a writing refusal of such a still is the[m
[32m+[m[32m    #: Director's to overturn (`may_be_overturned`), never a hard limit of the bible.[m
[32m+[m[32m    expected_markings: tuple[str, ...] = ()[m
 [m
 [m
 @dataclass(frozen=True)[m
[36m@@ -367,6 +373,8 @@[m [mclass StillReport:[m
     #: The items whose trace the look called minor: accepted, carried as a warning on the take[m
     #: (`fix_check.record_take_note`) and on the stills step's entry.[m
     minor: tuple[dict[str, str], ...] = ()[m
[32m+[m[32m    #: The plan's objects that carry their own markings (`StillPlan.expected_markings`).[m
[32m+[m[32m    expected_markings: tuple[str, ...] = ()[m
 [m
     @property[m
     def matched_plan(self) -> bool:[m
[36m@@ -1088,7 +1096,17 @@[m [mdef decide([m
                 )[m
                 violations.append("faces")[m
         if verdict.readable_text:[m
[31m-            vision_reasons.append(f"Modelul de vedere a văzut text lizibil în imagine {said}")[m
[32m+[m[32m            marked = tuple(getattr(plan, "expected_markings", ()) or ())[m
[32m+[m[32m            if marked:[m
[32m+[m[32m                # The plan asks for an object with its own scale: the look was told so, and[m
[32m+[m[32m                # what it still reads as writing is the Director's to judge (2026-10-13).[m
[32m+[m[32m                vision_reasons.append([m
[32m+[m[32m                    f"Modelul de vedere a văzut text lizibil în imagine, deși planul cere "[m
[32m+[m[32m                    f"{markings_ro(marked)}, care își poartă scala; Directoarea decide dacă "[m
[32m+[m[32m                    f"scrisul e al obiectului {said}"[m
[32m+[m[32m                )[m
[32m+[m[32m            else:[m
[32m+[m[32m                vision_reasons.append(f"Modelul de vedere a văzut text lizibil în imagine {said}")[m
             violations.append("readable_text")[m
         if not verdict.one_picture:[m
             # 2026-10-09: scene 5's triptych of three similar tunnels had no flat band to[m
[36m@@ -1148,6 +1166,7 @@[m [mdef decide([m
         measured=measured,[m
         fixes=tuple(fixes),[m
         minor=tuple(minor_traces(fixes)),[m
[32m+[m[32m        expected_markings=tuple(getattr(plan, "expected_markings", ()) or ()),[m
     )[m
 [m
 [m
[36m@@ -1199,19 +1218,34 @@[m [mdef may_be_overturned(report: StillReport) -> bool:[m
     is bought for its scene: a refusal the gate measured whole (nothing unmeasured) whose[m
     reasons are a reading — the plan, the scene, the look, the technique, a corrected mistake[m
     seen again — and none of the bible's hard limits (`fix_check.HARD_LIMITS`: a face where[m
[31m-    faces are forbidden, writing, panels, a blank field), which stay the code's."""[m
[32m+[m[32m    faces are forbidden, writing, panels, a blank field), which stay the code's. Writing on a[m
[32m+[m[32m    still whose plan asks for an object with its own markings (``expected_markings``) is a[m
[32m+[m[32m    reading, hers: a thermometer's scale is not the bible's writing (2026-10-13)."""[m
[32m+[m[32m    hard = set(report.violations) & HARD_LIMITS[m
[32m+[m[32m    if report.expected_markings:[m
[32m+[m[32m        hard.discard("readable_text")[m
     return ([m
         report.decision == "BLOCKED"[m
         and bool(report.violations)[m
         and not report.unmeasured[m
[31m-        and not set(report.violations) & HARD_LIMITS[m
[32m+[m[32m        and not hard[m
         and report.outcome != "compose_locally"[m
     )[m
 [m
 [m
[31m-def positive_instruction(violations: Iterable[str]) -> str:[m
[31m-    """The violations rewritten as words the image model obeys (English, for the model)."""[m
[31m-    words = [POSITIVE_WORDS[code] for code in dict.fromkeys(violations) if code in POSITIVE_WORDS][m
[32m+[m[32mdef positive_instruction(violations: Iterable[str], markings: Sequence[str] = ()) -> str:[m
[32m+[m[32m    """The violations rewritten as words the image model obeys (English, for the model). A[m
[32m+[m[32m    writing violation on a plan that asks for an object with its own markings (``markings``)[m
[32m+[m[32m    keeps that object's scale and asks every other surface plain (2026-10-13)."""[m
[32m+[m[32m    words: list[str] = [][m
[32m+[m[32m    for code in dict.fromkeys(violations):[m
[32m+[m[32m        if code == "readable_text" and markings:[m
[32m+[m[32m            words.append([m
[32m+[m[32m                f"only {named(markings)}'s own scale and markings, every other surface plain "[m
[32m+[m[32m                "and unmarked, signs left blank"[m
[32m+[m[32m            )[m
[32m+[m[32m        elif code in POSITIVE_WORDS:[m
[32m+[m[32m            words.append(POSITIVE_WORDS[code])[m
     return "; ".join(words)[m
 [m
 [m
[36m@@ -1280,7 +1314,7 @@[m [mdef next_step(report: StillReport, *, rerolls_done: int, words_correct: bool = F[m
     if rerolls_done < MAX_REROLLS:[m
         return NextStep([m
             "reroll",[m
[31m-            positive_instruction(report.violations),[m
[32m+[m[32m            positive_instruction(report.violations, report.expected_markings),[m
             f"Scena {report.scene}: imaginea se reface ({rerolls_done + 1}/{MAX_REROLLS}): {first}",[m
         )[m
     return NextStep([m
[1mdiff --git a/backend/app/media/stills_stage.py b/backend/app/media/stills_stage.py[m
[1mindex 3b0a9c0..6e0d683 100644[m
[1m--- a/backend/app/media/stills_stage.py[m
[1m+++ b/backend/app/media/stills_stage.py[m
[36m@@ -157,6 +157,7 @@[m [mfrom app.media.cost_plan import ([m
 from app.media.disk import LOW_DISK, disk_refusal[m
 from app.media.faces import FaceCounter[m
 from app.media.fix_check import STILL_LAYER, open_findings[m
[32m+[m[32mfrom app.media.markings import planned_markings[m
 from app.media.mode_guard import PurchaseGuard, unasked_refusal[m
 from app.media.models import SceneTake, Storyboard, StoryboardScene[m
 from app.media.picture_qc import StillJudgement, judge_still[m
[36m@@ -244,10 +245,25 @@[m [mdef _bible_bans_faces(bible: Mapping[str, Any] | None) -> bool:[m
     return any(BIBLE_NO_FACES.search(text) for text in texts)[m
 [m
 [m
[31m-def still_negative(package: Mapping[str, Any] | None, bible: Mapping[str, Any] | None) -> str:[m
[31m-    """The negative prompt of one still: `STILL_NEGATIVE`, the faces when the bible forbids[m
[31m-    them, then the plan's own `avoid` items, each once, within `NEGATIVE_CHARS`."""[m
[31m-    terms: list[str] = list(STILL_NEGATIVE)[m
[32m+[m[32m#: Of `STILL_NEGATIVE`, the terms a scene whose plan names an object with its own markings[m
[32m+[m[32m#: leaves out (`markings.planned_markings`, 2026-10-13): a negative channel told «text,[m
[32m+[m[32m#: lettering» beside «the thermometer keeps its scale» draws a blank instrument. Captions,[m
[32m+[m[32m#: subtitles, a logo and a watermark stay out of every still.[m
[32m+[m[32m_MARKED_OBJECT_KEEPS: frozenset[str] = frozenset({"text", "lettering"})[m
[32m+[m
[32m+[m
[32m+[m[32mdef still_negative([m
[32m+[m[32m    package: Mapping[str, Any] | None,[m
[32m+[m[32m    bible: Mapping[str, Any] | None,[m
[32m+[m[32m    markings: Sequence[str] = (),[m
[32m+[m[32m) -> str:[m
[32m+[m[32m    """The negative prompt of one still: `STILL_NEGATIVE` (without «text» and «lettering»[m
[32m+[m[32m    when the plan names an object that carries its own markings, ``markings``), the faces[m
[32m+[m[32m    when the bible forbids them, then the plan's own `avoid` items, each once, within[m
[32m+[m[32m    `NEGATIVE_CHARS`."""[m
[32m+[m[32m    terms: list[str] = [[m
[32m+[m[32m        term for term in STILL_NEGATIVE if not (markings and term in _MARKED_OBJECT_KEEPS)[m
[32m+[m[32m    ][m
     if _bible_bans_faces(bible):[m
         terms += STILL_NEGATIVE_FACES[m
     avoid = (package or {}).get("avoid")[m
[36m@@ -375,6 +391,9 @@[m [mclass _Scene:[m
     #: What the scene's current words were rewritten to fix (`fix_check.open_findings`), for[m
     #: the gate to verify on every still bought for it (`still_gate.StillPlan.must_fix`).[m
     must_fix: tuple[dict[str, str], ...] = ()[m
[32m+[m[32m    #: The plan's objects that carry their own markings (`markings.planned_markings`), for the[m
[32m+[m[32m    #: gate (`still_gate.StillPlan.expected_markings`): a thermometer's scale is not writing.[m
[32m+[m[32m    expected_markings: tuple[str, ...] = ()[m
 [m
 [m
 @dataclass[m
[36m@@ -483,6 +502,7 @@[m [mdef _still_plan(scene: _Scene, *, faces_forbidden: bool, rules: tuple[str, ...])[m
         narration=scene.narration,[m
         purpose=scene.purpose,[m
         must_fix=scene.must_fix,[m
[32m+[m[32m        expected_markings=scene.expected_markings,[m
     )[m
 [m
 [m
[36m@@ -533,6 +553,8 @@[m [mdef _read_scenes(engine: Engine, storyboard_id: str) -> tuple[dict[str, Any], li[m
                 except ReferenceRequired as exc:[m
                     missing = str(exc)[m
             identity = still_fields(visual, reference)[m
[32m+[m[32m            picture = _scene_picture(package, visual, words, serial=serial)[m
[32m+[m[32m            marked = planned_markings(words, picture)[m
             scene = _Scene([m
                 index=int(row.scene_index),[m
                 kind=kind,[m
[36m@@ -543,10 +565,11 @@[m [mdef _read_scenes(engine: Engine, storyboard_id: str) -> tuple[dict[str, Any], li[m
                 source=package.get("source") if isinstance(package.get("source"), str) else None,[m
                 reference=reference,[m
                 needs_reference=missing,[m
[31m-                negative=still_negative(package, bible),[m
[31m-                picture=_scene_picture(package, visual, words, serial=serial),[m
[32m+[m[32m                negative=still_negative(package, bible, marked),[m
[32m+[m[32m                picture=picture,[m
                 narration=" ".join(str(row.voiceover_segment or "").split()),[m
                 purpose=str(row.story_purpose or ""),[m
[32m+[m[32m                expected_markings=marked,[m
             )[m
             if kind == LIVE_KIND:[m
                 # The picture's open items only: a finding treated in the motion's words is[m
[1mdiff --git a/backend/app/runbook/stages.py b/backend/app/runbook/stages.py[m
[1mindex 298e537..b78b5c5 100644[m
[1m--- a/backend/app/runbook/stages.py[m
[1m+++ b/backend/app/runbook/stages.py[m
[36m@@ -5071,6 +5071,62 @@[m [mdef _still_newer_than_film(session: Session, storyboard_id: str, scene: int, ass[m
     return str(approved.id) != in_film.get("still")[m
 [m
 [m
[32m+[m[32mdef _corrected_for_film([m
[32m+[m[32m    session: Session, storyboard_id: str, scene: int, asset_id: str[m
[32m+[m[32m) -> dict[str, Any] | None:[m
[32m+[m[32m    """The scene's words as the Director's ladder corrected them for the failed film[m
[32m+[m[32m    ``asset_id`` and nobody bought on yet: her newest ``media.prompts_rewritten`` for the[m
[32m+[m[32m    scene, written after the film was rendered and after every take of the scene — {"layer",[m
[32m+[m[32m    "event_id"}; None when there is none (nothing corrected for this film, or a take bought on[m
[32m+[m[32m    the correction since).[m
[32m+[m
[32m+[m[32m    2026-10-13: a paid redo under his ask-me rule is corrected first (`_correct_before_redo`)[m
[32m+[m[32m    and then asked, his yes bound to the corrected plan; the walk that resumed after his yes[m
[32m+[m[32m    corrected the scene AGAIN before spending it — the same words came back and the redo was[m
[32m+[m[32m    refused PROMPT_NOT_CORRECTED, or new words made a new plan and he was asked again — so the[m
[32m+[m[32m    redo he approved was never bought. On the resume, words corrected for this film and not[m
[32m+[m[32m    bought yet are the words his yes was asked on: neither her look nor his rewrite is asked[m
[32m+[m[32m    again before it is spent (`_apply_repairs`)."""[m
[32m+[m[32m    from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT  # noqa: PLC0415[m
[32m+[m[32m    from app.media.models import SceneTake  # noqa: PLC0415[m
[32m+[m[32m    from app.media.scene_rewrite import DECIDED_BY, REWRITE_REASON, _after  # noqa: PLC0415[m
[32m+[m
[32m+[m[32m    film = session.get(MediaAsset, asset_id) if asset_id else None[m
[32m+[m[32m    if film is None:[m
[32m+[m[32m        return None[m
[32m+[m[32m    newest_take = session.scalar([m
[32m+[m[32m        select(SceneTake.created_at)[m
[32m+[m[32m        .where(SceneTake.storyboard_id == storyboard_id, SceneTake.scene_number == scene)[m
[32m+[m[32m        .order_by(SceneTake.created_at.desc())[m
[32m+[m[32m        .limit(1)[m
[32m+[m[32m    )[m
[32m+[m[32m    floor = str(film.created_at or "")[m
[32m+[m[32m    if newest_take and _after(newest_take, floor):[m
[32m+[m[32m        floor = str(newest_take)[m
[32m+[m[32m    for event in session.scalars([m
[32m+[m[32m        select(DomainEvent)[m
[32m+[m[32m        .where([m
[32m+[m[32m            DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT,[m
[32m+[m[32m            DomainEvent.aggregate_id == storyboard_id,[m
[32m+[m[32m        )[m
[32m+[m[32m        .order_by(DomainEvent.sequence.desc())[m
[32m+[m[32m    ):[m
[32m+[m[32m        payload = event.payload if isinstance(event.payload, dict) else {}[m
[32m+[m[32m        if payload.get("scene_index") != scene:[m
[32m+[m[32m            continue[m
[32m+[m[32m        # Only her brief's rewrite (`scene_rewrite.REWRITE_REASON`): the serial's[m
[32m+[m[32m        # recomposition and its technical re-roll write the same event as the Director's,[m
[32m+[m[32m        # on words that may not have changed (the Codex review of c6dc05c).[m
[32m+[m[32m        if ([m
[32m+[m[32m            payload.get("decided_by") != DECIDED_BY[m
[32m+[m[32m            or payload.get("reason") != REWRITE_REASON[m
[32m+[m[32m            or not _after(event.timestamp, floor)[m
[32m+[m[32m        ):[m
[32m+[m[32m            return None[m
[32m+[m[32m        return {"layer": payload.get("layer"), "event_id": str(event.event_id)}[m
[32m+[m[32m    return None[m
[32m+[m
[32m+[m
 def _correct_before_redo([m
     engine: Engine,[m
     registry: ProviderRegistry | None,[m
[36m@@ -5663,7 +5719,18 @@[m [mdef _apply_repairs([m
                 {"scene_index": scene, "per_scene": per_scene, "per_film": per_film}[m
             )[m
             continue[m
[32m+[m[32m        corrected = None[m
         if continues is None:[m
[32m+[m[32m            with Session(engine) as session:[m
[32m+[m[32m                corrected = _corrected_for_film(session, storyboard_id, scene, asset_id)[m
[32m+[m[32m        if corrected is not None:[m
[32m+[m[32m            # The words his yes was asked on (2026-10-13, `_corrected_for_film`): the walk[m
[32m+[m[32m            # that resumes after it neither looks nor corrects again before spending it. A[m
[32m+[m[32m            # correction that turned to the picture buys the still and its motion, as the[m
[32m+[m[32m            # first walk did.[m
[32m+[m[32m            if corrected.get("layer") == "still" and "still" not in paid[scene]:[m
[32m+[m[32m                paid[scene].insert(0, "still")[m
[32m+[m[32m        elif continues is None:[m
             # She looks at the scene once more before anything is bought for it (2026-10-12):[m
             # free, and the purchase is not. The motion that continues a new still was looked[m
             # at with that still.[m
[1mdiff --git a/tests/test_director_rewrites_failed_scene.py b/tests/test_director_rewrites_failed_scene.py[m
[1mindex af03fe9..bc0cfec 100644[m
[1m--- a/tests/test_director_rewrites_failed_scene.py[m
[1m+++ b/tests/test_director_rewrites_failed_scene.py[m
[36m@@ -14,6 +14,7 @@[m [mfrom app.agents.models import Agent, AgentMessage, ModelRecord, Role[m
 from app.agents.services import seed_initial_workforce[m
 from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT, motion_plan[m
 from app.media.models import SceneTake, StoryboardScene[m
[32m+[m[32mfrom app.media.prompt_agent import motion_prompt_for[m
 from app.media.scene_rewrite import ([m
     BRIEF_EVENT,[m
     MOTION,[m
[36m@@ -290,7 +291,11 @@[m [mdef test_her_brief_rewrites_the_motion_and_the_shot_is_bought_again_and_passes([m
         clip_check=ScriptedCheck("PASSED"),[m
     )[m
     assert models.posts() == posted + 1[m
[31m-    assert spy.asked[-1]["prompt"] != spy.asked[0]["prompt"][m
[32m+[m[32m    # The words sent are the rewritten package as rendered, not merely other words[m
[32m+[m[32m    # (2026-10-13): a retry's firmer prompt or a stale intent would also differ.[m
[32m+[m[32m    expected, _negative = motion_prompt_for(after.prompt_json, "seedance2_5", None)[m
[32m+[m[32m    assert spy.asked[-1]["prompt"] == expected[m
[32m+[m[32m    assert "from left to right" in expected and "from left to right" not in spy.asked[0]["prompt"][m
     (entry,) = summary["scenes"][m
     assert entry["status"] == "PAID"[m
 [m
[1mdiff --git a/tests/test_planned_markings.py b/tests/test_planned_markings.py[m
[1mnew file mode 100644[m
[1mindex 0000000..720b402[m
[1m--- /dev/null[m
[1m+++ b/tests/test_planned_markings.py[m
[36m@@ -0,0 +1,368 @@[m
[32m+[m[32m"""Writing that belongs to the object the plan asks for (2026-10-13).[m
[32m+[m
[32m+[m[32mThe Owner, on the film «Why the Kelvin Scale Has No 'Zero' to Begin From»: a scene asked for a[m
[32m+[m[32mthermometer and quality control refused every still for the digits on it. «Nu ai cum să ai un[m
[32m+[m[32mtermometru fără scris, grade, Celsius.» Offline, with faked models and vendors:[m
[32m+[m
[32m+[m[32m- the plan's objects that carry their own markings are read from its words (`planned_markings`);[m
[32m+[m[32m- writing on such an object is no hard limit of the bible: the Director overturns it in one[m
[32m+[m[32m  look, without the fail-closed loop, while the same words on a plan of plain objects still[m
[32m+[m[32m  fail closed; her rewrite review does not anchor such a finding serious;[m
[32m+[m[32m- the stills gate leaves such a writing refusal to her look (never a blind re-roll), its words[m
[32m+[m[32m  tell the Owner why, and a re-roll keeps the object's scale;[m
[32m+[m[32m- the look that judges the still is told the instrument keeps its scale; the stills step asks[m
[32m+[m[32m  her before anything more is bought; a clip's writing refusal is hers to overturn too;[m
[32m+[m[32m- the still prompt says the object keeps its markings instead of «No text».[m
[32m+[m[32m"""[m
[32m+[m
[32m+[m[32mfrom __future__ import annotations[m
[32m+[m
[32m+[m[32mimport json[m
[32m+[m[32mfrom typing import Any[m
[32m+[m
[32m+[m[32mimport pytest[m
[32m+[m[32mfrom app.media import fix_check[m
[32m+[m[32mfrom app.media.markings import ([m
[32m+[m[32m    markings_kept,[m
[32m+[m[32m    markings_note,[m
[32m+[m[32m    markings_ro,[m
[32m+[m[32m    planned_markings,[m
[32m+[m[32m    still_exclusions,[m
[32m+[m[32m)[m
[32m+[m[32mfrom app.media.models import StoryboardScene[m
[32m+[m[32mfrom app.media.picture_qc import judge_still[m
[32m+[m[32mfrom app.media.prompt_agent import compile_prompts[m
[32m+[m[32mfrom app.media.prompt_lint import has_block, lint_still_prompt[m
[32m+[m[32mfrom app.media.qc import ClipCheck, ClipReport, look_may_overturn[m
[32m+[m[32mfrom app.media.scene_rewrite import hard_limit[m
[32m+[m[32mfrom app.media.second_look import HARD_LIMIT_MARK, hard_limits[m
[32m+[m[32mfrom app.media.still_gate import StillPlan, decide, may_be_overturned, positive_instruction[m
[32m+[m[32mfrom app.media.stills_stage import still_negative[m
[32m+[m[32mfrom app.media.toolchain import find_ffmpeg[m
[32m+[m[32mfrom app.providers.base import GenerateResult, HealthResult[m
[32m+[m[32mfrom sqlalchemy import select[m
[32m+[m[32mfrom sqlalchemy.orm import Session[m
[32m+[m[32mfrom test_director_decides_qc import failed_film[m
[32m+[m[32mfrom test_fix_is_verified import HER, Looks, OffPlanFirst, new_pictures_for, verdict[m
[32m+[m[32mfrom test_second_look import ([m
[32m+[m[32m    FIXTURES,[m
[32m+[m[32m    LookingDirector,[m
[32m+[m[32m    events,[m
[32m+[m[32m    give_vision,[m
[32m+[m[32m    her_registry,[m
[32m+[m[32m    look,[m
[32m+[m[32m    seeded_studio,[m
[32m+[m[32m    shown,[m
[32m+[m[32m)[m
[32m+[m[32mfrom test_stills_stage import LOOK, SUBJECTS, TAIL, SpyStills, a_film, approved_run[m
[32m+[m
[32m+[m[32mrequires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")[m
[32m+[m
[32m+[m[32mTHERMOMETER = ([m
[32m+[m[32m    "Detail shot, 85mm lens. A mercury thermometer with its Celsius scale on a lab bench, one "[m
[32m+[m[32m    "cold lamp. Vertical 9:16 frame, main subject in the upper two thirds."[m
[32m+[m[32m)[m
[32m+[m[32mWRITING = "Modelul de vedere a văzut text lizibil în imagine («digits along the thermometer»)"[m
[32m+[m[32m#: Her look at the digits: the scale is the thermometer's, the picture is used.[m
[32m+[m[32mITS_SCALE = {[m
[32m+[m[32m    "verdict": "OVERTURNED",[m
[32m+[m[32m    "severity": "minor",[m
[32m+[m[32m    "redo": False,[m
[32m+[m[32m    "reason_ro": "Văd doar scala termometrului cu gradele ei; nu e text în imagine.",[m
[32m+[m[32m    "cause": "Planul cere un termometru, iar modelul de vedere a citit scala lui ca text.",[m
[32m+[m[32m    "layer": "still",[m
[32m+[m[32m}[m
[32m+[m
[32m+[m
[32m+[m[32m# ------------------------------------------------------------------- the objects a plan names[m
[32m+[m
[32m+[m
[32m+[m[32m@pytest.mark.parametrize([m
[32m+[m[32m    ("text", "found"),[m
[32m+[m[32m    [[m
[32m+[m[32m        ("A mercury thermometer with its Celsius scale on a lab bench", ("thermometer",)),[m
[32m+[m[32m        ("un termometru vechi pe masa laboratorului", ("thermometer",)),[m
[32m+[m[32m        ("a brass pressure gauge beside a wall clock", ("gauge", "clock")),[m
[32m+[m[32m        ("the Kelvin scale drawn as a tall vertical line", ("temperature scale",)),[m
[32m+[m[32m        ("A far village of stone houses on a terraced slope", ()),[m
[32m+[m[32m        ("a blank sign over a shop, a page of a book", ()),[m
[32m+[m[32m        ("the valley lit at six o'clock in the evening", ()),[m
[32m+[m[32m        (None, ()),[m
[32m+[m[32m    ],[m
[32m+[m[32m)[m
[32m+[m[32mdef test_the_objects_a_plan_names(text, found):[m
[32m+[m[32m    assert planned_markings(text) == found[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_words_for_the_models_and_the_owner():[m
[32m+[m[32m    assert still_exclusions(()) == "No text, no logo."[m
[32m+[m[32m    assert still_exclusions(("thermometer",)) == ([m
[32m+[m[32m        "The thermometer keeps its own scale and markings; no caption, no logo."[m
[32m+[m[32m    )[m
[32m+[m[32m    assert still_exclusions(("thermometer", "gauge")).startswith([m
[32m+[m[32m        "The thermometer and the gauge keep their own"[m
[32m+[m[32m    )[m
[32m+[m[32m    assert markings_kept(("clock",)) == "The clock keeps its own scale and markings."[m
[32m+[m[32m    assert markings_note(("thermometer",)).startswith("The plan asks for a thermometer:")[m
[32m+[m[32m    assert "only writing elsewhere" in markings_note(("thermometer",))[m
[32m+[m[32m    assert "no reason for compose_locally" in markings_note(("thermometer",))[m
[32m+[m[32m    assert markings_note(()) == "" and markings_kept(()) == ""[m
[32m+[m[32m    assert markings_ro(("thermometer", "gauge")) == "termometrul și indicatorul cu cadran"[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_still_prompt_lets_the_instrument_keep_its_scale():[m
[32m+[m[32m    package = {[m
[32m+[m[32m        "scene_index": 3,[m
[32m+[m[32m        "scene_kind": "LIVE",[m
[32m+[m[32m        "subject": "a mercury thermometer on a lab bench",[m
[32m+[m[32m        "environment": "a dim laboratory",[m
[32m+[m[32m        "camera": "detail shot, 85mm lens",[m
[32m+[m[32m        "lighting": "one cold lamp",[m
[32m+[m[32m        "motion": "the mercury climbs",[m
[32m+[m[32m        "camera_move": "slow push-in",[m
[32m+[m[32m    }[m
[32m+[m[32m    still = compile_prompts(package, {})["still_prompt"][m
[32m+[m[32m    assert still.endswith("The thermometer keeps its own scale and markings; no caption, no logo.")[m
[32m+[m[32m    assert "No text" not in still[m
[32m+[m[32m    assert not has_block(lint_still_prompt(still, scene=3))[m
[32m+[m[32m    plain = compile_prompts({**package, "subject": "a cold lamp on a lab bench"}, {})[m
[32m+[m[32m    assert plain["still_prompt"].endswith("No text, no logo.")[m
[32m+[m
[32m+[m
[32m+[m[32m# ------------------------------------------------------------ no hard limit, hers to judge[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_writing_on_the_planned_object_is_no_hard_limit():[m
[32m+[m[32m    assert hard_limits([WRITING], faces_forbidden=False) == ["writing"][m
[32m+[m[32m    assert hard_limits([WRITING], faces_forbidden=False, markings=("thermometer",)) == [][m
[32m+[m[32m    # Faces and panels stay what they are.[m
[32m+[m[32m    face = "YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele"[m
[32m+[m[32m    assert hard_limits([face, WRITING], faces_forbidden=True, markings=("thermometer",)) == [[m
[32m+[m[32m        "faces"[m
[32m+[m[32m    ][m
[32m+[m[32m    assert hard_limits(["o bandă plată între panouri"], faces_forbidden=False, markings=("x",)) == [[m
[32m+[m[32m        "panels"[m
[32m+[m[32m    ][m
[32m+[m[32m    # Her review of a rewrite does not anchor such a finding serious either.[m
[32m+[m[32m    assert hard_limit("Modelul de vedere a văzut text lizibil în imagine", {}) is True[m
[32m+[m[32m    assert ([m
[32m+[m[32m        hard_limit("Modelul de vedere a văzut text lizibil în imagine", {}, ("thermometer",))[m
[32m+[m[32m        is False[m
[32m+[m[32m    )[m
[32m+[m[32m    assert hard_limit("Imaginea nu e o singură fotografie: panouri", {}, ("thermometer",)) is True[m
[32m+[m
[32m+[m
[32m+[m[32mdef _plan_asks_for_a_thermometer(engine, film) -> None:[m
[32m+[m[32m    with Session(engine) as session, session.begin():[m
[32m+[m[32m        row = session.scalar([m
[32m+[m[32m            select(StoryboardScene).where([m
[32m+[m[32m                StoryboardScene.storyboard_id == film["board"], StoryboardScene.scene_index == 5[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
[32m+[m[32m        row.prompt_json = {**dict(row.prompt_json or {}), "still_prompt": THERMOMETER}[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_she_overturns_the_digits_on_a_thermometer_in_one_look(engine):[m
[32m+[m[32m    studio = seeded_studio(engine)[m
[32m+[m[32m    film = failed_film(engine)[m
[32m+[m[32m    _plan_asks_for_a_thermometer(engine, film)[m
[32m+[m[32m    give_vision(engine, studio["agents"]["Director"].model_id)[m
[32m+[m[32m    model = LookingDirector(ITS_SCALE)[m
[32m+[m
[32m+[m[32m    result = look(engine, her_registry(studio, model), film, refusal=[WRITING])[m
[32m+[m
[32m+[m[32m    assert (result["verdict"], result["severity"], result["redo"]) == ("OVERTURNED", "minor", False)[m
[32m+[m[32m    assert result["cause"] == ITS_SCALE["cause"][m
[32m+[m[32m    ((prompt, _images, _model),) = model.looked[m
[32m+[m[32m    assert "The plan asks for a thermometer" in prompt and HARD_LIMIT_MARK not in prompt[m
[32m+[m[32m    assert "only such an object's own scale is no defect" in prompt[m
[32m+[m[32m    data = shown(prompt)[m
[32m+[m[32m    assert data["planned_markings"] == ["thermometer"] and "hard_limits" not in data[m
[32m+[m[32m    assert data["scene"]["plan"]["planned_markings"] == ["thermometer"][m
[32m+[m[32m    (event,) = events(engine)[m
[32m+[m[32m    assert event["planned_markings"] == ["thermometer"] and event["hard_limits"] == [][m
[32m+[m[32m    assert event["verdict"] == "OVERTURNED" and event["fail_closed"] is False[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_same_writing_on_a_plan_of_plain_objects_still_fails_closed(engine):[m
[32m+[m[32m    studio = seeded_studio(engine)[m
[32m+[m[32m    film = failed_film(engine)[m
[32m+[m[32m    give_vision(engine, studio["agents"]["Director"].model_id)[m
[32m+[m[32m    model = LookingDirector(ITS_SCALE)[m
[32m+[m
[32m+[m[32m    result = look(engine, her_registry(studio, model), film, refusal=[WRITING])[m
[32m+[m
[32m+[m[32m    assert len(model.looked) == 2[m
[32m+[m[32m    assert (result["verdict"], result["severity"], result["redo"]) == ("CONFIRMED", "serious", True)[m
[32m+[m[32m    (event,) = events(engine)[m
[32m+[m[32m    assert event["hard_limits"] == ["writing"] and "planned_markings" not in event[m
[32m+[m[32m    assert event["fail_closed"] is True[m
[32m+[m
[32m+[m
[32m+[m[32m# --------------------------------------------------------------------------- the stills gate[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_gate_leaves_such_a_writing_refusal_to_her_look():[m
[32m+[m[32m    plan = StillPlan([m
[32m+[m[32m        scene=4,[m
[32m+[m[32m        still_prompt=THERMOMETER,[m
[32m+[m[32m        camera_move="slow push-in",[m
[32m+[m[32m        faces_forbidden=False,[m
[32m+[m[32m        expected_markings=("thermometer",),[m
[32m+[m[32m    )[m
[32m+[m[32m    plain = StillPlan(scene=4, still_prompt="A cold lamp.", camera_move="", faces_forbidden=False)[m
[32m+[m[32m    picture = FIXTURES / "scene_01.jpg"[m
[32m+[m
[32m+[m[32m    digits = decide(picture, plan, [], verdict(readable_text=True), environment="TEST")[m
[32m+[m[32m    lettering = decide(picture, plain, [], verdict(readable_text=True), environment="TEST")[m
[32m+[m
[32m+[m[32m    assert digits.decision == "BLOCKED" and "readable_text" in digits.violations[m
[32m+[m[32m    assert digits.expected_markings == ("thermometer",)[m
[32m+[m[32m    assert may_be_overturned(digits) and not may_be_overturned(lettering)[m
[32m+[m[32m    assert "deși planul cere termometrul" in digits.reasons_ro[0][m
[32m+[m[32m    assert "Directoarea decide" in digits.reasons_ro[0][m
[32m+[m[32m    assert ([m
[32m+[m[32m        "text lizibil" in lettering.reasons_ro[0] and "termometrul" not in lettering.reasons_ro[0][m
[32m+[m[32m    )[m
[32m+[m[32m    # Panels on the same still stay the code's.[m
[32m+[m[32m    panels = decide([m
[32m+[m[32m        picture, plan, [], verdict(readable_text=True, one_picture=False), environment="TEST"[m
[32m+[m[32m    )[m
[32m+[m[32m    assert not may_be_overturned(panels)[m
[32m+[m[32m    # A re-roll keeps the instrument's scale and asks every other surface plain.[m
[32m+[m[32m    words = positive_instruction(["readable_text"], ("thermometer",))[m
[32m+[m[32m    assert "the thermometer's own scale" in words and "plain" in words[m
[32m+[m[32m    assert positive_instruction(["readable_text"]).startswith("plain surfaces")[m
[32m+[m
[32m+[m
[32m+[m[32mclass SeeingModel:[m
[32m+[m[32m    """The looker's model, faked: answers any look with a still that is right, every prompt[m
[32m+[m[32m    kept."""[m
[32m+[m
[32m+[m[32m    def __init__(self):[m
[32m+[m[32m        self.calls: list[str] = [][m
[32m+[m
[32m+[m[32m    async def health_check(self):[m
[32m+[m[32m        return HealthResult("HEALTHY")[m
[32m+[m
[32m+[m[32m    async def list_models(self):[m
[32m+[m[32m        return [][m
[32m+[m
[32m+[m[32m    async def generate(self, model, prompt, **kwargs):[m
[32m+[m[32m        self.calls.append(prompt)[m
[32m+[m[32m        answer: dict[str, Any] = {[m
[32m+[m[32m            "stills": [[m
[32m+[m[32m                {[m
[32m+[m[32m                    "scene": 4,[m
[32m+[m[32m                    "faces_visible": False,[m
[32m+[m[32m                    "readable_text": False,[m
[32m+[m[32m                    "one_picture": True,[m
[32m+[m[32m                    "matches_plan": True,[m
[32m+[m[32m                    "shows_scene": True,[m
[32m+[m[32m                    "look_ok": True,[m
[32m+[m[32m                    "technical_ok": True,[m
[32m+[m[32m                    "bible_violations": "none",[m
[32m+[m[32m                    "verdict": "buy_motion",[m
[32m+[m[32m                    "reason": "a thermometer on a bench, its scale readable",[m
[32m+[m[32m                }[m
[32m+[m[32m            ][m
[32m+[m[32m        }[m
[32m+[m[32m        return GenerateResult(json.dumps(answer), 10, 40, None)[m
[32m+[m
[32m+[m
[32m+[m[32m@requires_ffmpeg[m
[32m+[m[32mdef test_the_look_is_told_the_instrument_keeps_its_scale(engine):[m
[32m+[m[32m    studio = seeded_studio(engine)[m
[32m+[m[32m    give_vision(engine, studio["agents"]["VideoEditor"].model_id)[m
[32m+[m[32m    model = SeeingModel()[m
[32m+[m[32m    registry = her_registry(studio, model)[m
[32m+[m[32m    plan = StillPlan([m
[32m+[m[32m        scene=4,[m
[32m+[m[32m        still_prompt=THERMOMETER,[m
[32m+[m[32m        camera_move="",[m
[32m+[m[32m        faces_forbidden=False,[m
[32m+[m[32m        expected_markings=("thermometer",),[m
[32m+[m[32m    )[m
[32m+[m[32m    plain = StillPlan(scene=4, still_prompt="A cold lamp.", camera_move="", faces_forbidden=False)[m
[32m+[m
[32m+[m[32m    told = judge_still(engine, registry, FIXTURES / "scene_01.jpg", plan, "c-markings")[m
[32m+[m[32m    not_told = judge_still(engine, registry, FIXTURES / "scene_01.jpg", plain, "c-plain")[m
[32m+[m
[32m+[m[32m    assert told.status == "MEASURED" and not_told.status == "MEASURED"[m
[32m+[m[32m    first, second = model.calls[m
[32m+[m[32m    assert ([m
[32m+[m[32m        "The plan asks for a thermometer" in first[m
[32m+[m[32m        and '"planned_markings": ["thermometer"]' in first[m
[32m+[m[32m    )[m
[32m+[m[32m    assert "The plan asks for" not in second and "planned_markings" not in second[m
[32m+[m
[32m+[m
[32m+[m[32m@requires_ffmpeg[m
[32m+[m[32mdef test_the_stills_step_asks_her_about_the_thermometers_digits(engine, tmp_path, monkeypatch):[m
[32m+[m[32m    """As `test_her_look_never_overturns_the_bibles_hard_limits`, with scene 2's plan asking[m
[32m+[m[32m    for a thermometer: the lettering the look reads is hers to judge, and her look keeps the[m
[32m+[m[32m    picture, so nothing more is bought."""[m
[32m+[m[32m    looks = Looks(HER["OVERTURNED"])[m
[32m+[m[32m    monkeypatch.setattr(fix_check, "director_second_look", looks)[m
[32m+[m[32m    storyboard_id = a_film(engine, tmp_path)[m
[32m+[m[32m    with Session(engine) as session, session.begin():[m
[32m+[m[32m        row = session.scalar([m
[32m+[m[32m            select(StoryboardScene).where([m
[32m+[m[32m                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 2[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
[32m+[m[32m        words = ([m
[32m+[m[32m            f"{LOOK} {SUBJECTS[2]} A mercury thermometer with its Celsius scale on a stone. {TAIL}"[m
[32m+[m[32m        )[m
[32m+[m[32m        row.visual_prompt = words[m
[32m+[m[32m        row.prompt_json = {**dict(row.prompt_json or {}), "still_prompt": words}[m
[32m+[m[32m    adapter = SpyStills(pictures=new_pictures_for(2))[m
[32m+[m
[32m+[m[32m    result = approved_run(engine, storyboard_id, tmp_path, adapter, OffPlanFirst(lettering=True))[m
[32m+[m
[32m+[m[32m    assert len(looks.asked) == 1, "the digits on the thermometer are hers to judge"[m
[32m+[m[32m    asked = looks.asked[0][m
[32m+[m[32m    assert asked["scene_index"] == 2 and asked["kind"] == "still"[m
[32m+[m[32m    assert any("termometrul" in reason for reason in asked["refusal"])[m
[32m+[m[32m    assert len([c for c in adapter.asked if SUBJECTS[2] in c["prompt"]]) == 1, "no re-roll"[m
[32m+[m[32m    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}[m
[32m+[m[32m    assert by_scene[2]["status"] == "APPROVED" and by_scene[2]["approved_by"] == "director_look"[m
[32m+[m
[32m+[m
[32m+[m[32m# ------------------------------------------------------------------------------- the clip[m
[32m+[m
[32m+[m
[32m+[m[32mdef _clip_refused_for_writing(**picture: Any) -> ClipReport:[m
[32m+[m[32m    return ClipReport([m
[32m+[m[32m        scene=1,[m
[32m+[m[32m        path="clip.mp4",[m
[32m+[m[32m        checks=([m
[32m+[m[32m            ClipCheck("motion", "PASSED", False, 0.5, "mișcare"),[m
[32m+[m[32m            ClipCheck("picture", "FAILED", True, None, "apare text sau un logo"),[m
[32m+[m[32m        ),[m
[32m+[m[32m        passed=False,[m
[32m+[m[32m        blocks_ro=("apare text sau un logo",),[m
[32m+[m[32m        warnings_ro=(),[m
[32m+[m[32m        unmeasured=(),[m
[32m+[m[32m        measured={"picture": {"verdict": {"readable_text": True, "one_picture": True}, **picture}},[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_a_clips_writing_on_the_planned_object_is_hers_to_overturn():[m
[32m+[m[32m    assert not look_may_overturn(_clip_refused_for_writing())[m
[32m+[m[32m    assert look_may_overturn(_clip_refused_for_writing(planned_markings=["thermometer"]))[m
[32m+[m
[32m+[m
[32m+[m[32m# ------------------------------------------------------------------- the negative channel[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_negative_channel_keeps_the_instruments_markings():[m
[32m+[m[32m    """The Codex review of c6dc05c: a negative prompt told «text, lettering» beside «the[m
[32m+[m[32m    thermometer keeps its scale» draws a blank instrument. Captions, a logo and a watermark[m
[32m+[m[32m    stay out of every still."""[m
[32m+[m[32m    plain = still_negative({}, {})[m
[32m+[m[32m    marked = still_negative({}, {}, ("thermometer",))[m
[32m+[m[32m    assert "text" in plain.split(", ") and "lettering" in plain.split(", ")[m
[32m+[m[32m    assert "text" not in marked.split(", ") and "lettering" not in marked.split(", ")[m
[32m+[m[32m    for kept in ("captions", "subtitles", "logo", "watermark", "panels"):[m
[32m+[m[32m        assert kept in marked.split(", ")[m
[1mdiff --git a/tests/test_redo_resume_spends_his_yes.py b/tests/test_redo_resume_spends_his_yes.py[m
[1mnew file mode 100644[m
[1mindex 0000000..277fbdf[m
[1m--- /dev/null[m
[1m+++ b/tests/test_redo_resume_spends_his_yes.py[m
[36m@@ -0,0 +1,244 @@[m
[32m+[m[32m"""His yes for a corrected paid redo is spent on the resume, not asked again (2026-10-13).[m
[32m+[m
[32m+[m[32mUnder the Owner's ask-me rule a paid REPAIR of a scene is corrected first (`_correct_before_redo`:[m
[32m+[m[32mher brief, his rewrite, her review, the new words stored) and then asked, his yes bound to the[m
[32m+[m[32mcorrected plan. Read on the source on 2026-10-13: the walk that resumed after his yes corrected[m
[32m+[m[32mthe scene AGAIN before spending it — the same words came back and the redo was refused[m
[32m+[m[32mPROMPT_NOT_CORRECTED, or new words made a new plan and he was asked again — so the redo he[m
[32m+[m[32mapproved was never bought. Now the words corrected for this film and not bought yet are the[m
[32m+[m[32mwords his yes was asked on (`stages._corrected_for_film`): the resume neither looks nor[m
[32m+[m[32mcorrects again, and the clip is bought on them.[m
[32m+[m
[32m+[m[32mOffline: `_apply_repairs` twice on one motion redo, faked vendor, scripted agents."""[m
[32m+[m
[32m+[m[32mfrom __future__ import annotations[m
[32m+[m
[32m+[m[32mfrom types import SimpleNamespace[m
[32m+[m[32mfrom uuid import uuid4[m
[32m+[m
[32m+[m[32mimport pytest[m
[32m+[m[32mfrom app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT[m
[32m+[m[32mfrom app.media.models import MediaAsset, SceneTake, VideoRenderJob[m
[32m+[m[32mfrom app.media.prompt_agent import motion_prompt_for[m
[32m+[m[32mfrom app.media.scene_rewrite import BRIEF_EVENT, REWRITE_REASON, SERIAL_RECOMPOSE_REASON[m
[32m+[m[32mfrom app.media.toolchain import find_ffmpeg[m
[32m+[m[32mfrom app.models import ApprovalRequest, OwnerPolicy[m
[32m+[m[32mfrom app.runbook import stages[m
[32m+[m[32mfrom app.services import append_event, utc_now[m
[32m+[m[32mfrom sqlalchemy import select[m
[32m+[m[32mfrom sqlalchemy.orm import Session[m
[32m+[m[32mfrom test_approvals import answer[m
[32m+[m[32mfrom test_clip_qc_wiring import events[m
[32m+[m[32mfrom test_director_rewrites_failed_scene import (  # noqa: F401 - the studio fixture[m
[32m+[m[32m    SHOT,[m
[32m+[m[32m    Agents,[m
[32m+[m[32m    a_planned_film,[m
[32m+[m[32m    agents_say,[m
[32m+[m[32m    scene,[m
[32m+[m[32m    studio,[m
[32m+[m[32m)[m
[32m+[m[32mfrom test_film_costing import SEEDANCE, Account, Models, SpyVideo[m
[32m+[m
[32m+[m[32mpytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")[m
[32m+[m
[32m+[m[32m#: What the editor would write if asked again on the resume: other words, another plan.[m
[32m+[m[32mSHOT_V3 = {[m
[32m+[m[32m    **SHOT,[m
[32m+[m[32m    "motion": "a shaft of sunlight sweeps across the terraces as the cloud breaks",[m
[32m+[m[32m    "camera_move": "slow push-in",[m
[32m+[m[32m    "ending_frame": "the village lit by a passing shaft of light",[m
[32m+[m[32m}[m
[32m+[m
[32m+[m
[32m+[m[32mdef _rewrites(engine, storyboard_id: str) -> list:[m
[32m+[m[32m    return [[m
[32m+[m[32m        e[m
[32m+[m[32m        for e in events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, storyboard_id)[m
[32m+[m[32m        if e.payload.get("decided_by") == "director"[m
[32m+[m[32m    ][m
[32m+[m
[32m+[m
[32m+[m[32mdef _walk(engine, settings, registry, storyboard_id: str, reading: dict) -> dict:[m
[32m+[m[32m    result: dict = {[m
[32m+[m[32m        "applied": [],[m
[32m+[m[32m        "bought": [],[m
[32m+[m[32m        "asked": [],[m
[32m+[m[32m        "refused": [],[m
[32m+[m[32m        "limited": [],[m
[32m+[m[32m        "made": [],[m
[32m+[m[32m        "new_asset": None,[m
[32m+[m[32m        "waiting": [],[m
[32m+[m[32m        "skipped": [],[m
[32m+[m[32m        "replaced_his": [],[m
[32m+[m[32m        "overturned": [],[m
[32m+[m[32m        "requalified": None,[m
[32m+[m[32m        "requalified_report_id": None,[m
[32m+[m[32m        "card_id": None,[m
[32m+[m[32m    }[m
[32m+[m[32m    stages._apply_repairs(engine, settings, None, registry, reading, result, False, str(uuid4()))[m
[32m+[m[32m    return result[m
[32m+[m
[32m+[m
[32m+[m[32mdef _failed_film(engine, tmp_path, storyboard_id: str) -> str:[m
[32m+[m[32m    """The failed film's render record: scene 1's clip made from its approved still, so the[m
[32m+[m[32m    still is not newer than the film (`_still_newer_than_film` False, as in a real film)."""[m
[32m+[m[32m    asset_id = str(uuid4())[m
[32m+[m[32m    with Session(engine) as session, session.begin():[m
[32m+[m[32m        still = session.scalar([m
[32m+[m[32m            select(SceneTake).where([m
[32m+[m[32m                SceneTake.storyboard_id == storyboard_id, SceneTake.kind == "still"[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
[32m+[m[32m        session.add([m
[32m+[m[32m            MediaAsset([m
[32m+[m[32m                id=asset_id,[m
[32m+[m[32m                asset_type="RENDERED_VIDEO",[m
[32m+[m[32m                uri_or_path=str(tmp_path / f"{asset_id}.mp4"),[m
[32m+[m[32m                file_size_bytes=1024,[m
[32m+[m[32m                mime_type="video/mp4",[m
[32m+[m[32m                provider_name="STUDIO_INTERNAL",[m
[32m+[m[32m                license_status="PROPRIETARY_STUDIO",[m
[32m+[m[32m                provenance_hash="a" * 64,[m
[32m+[m[32m                created_at=utc_now(),[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
[32m+[m[32m        session.flush()[m
[32m+[m[32m        session.add([m
[32m+[m[32m            VideoRenderJob([m
[32m+[m[32m                id=str(uuid4()),[m
[32m+[m[32m                storyboard_id=storyboard_id,[m
[32m+[m[32m                output_asset_id=asset_id,[m
[32m+[m[32m                status="COMPLETED",[m
[32m+[m[32m                production_json={[m
[32m+[m[32m                    "scenes": [[m
[32m+[m[32m                        {"scene_index": 1, "still_take": {"take_id": still.id}, "motion": None}[m
[32m+[m[32m                    ][m
[32m+[m[32m                },[m
[32m+[m[32m                started_at=utc_now(),[m
[32m+[m[32m                finished_at=utc_now(),[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
[32m+[m[32m    return asset_id[m
[32m+[m
[32m+[m
[32m+[m[32m@pytest.mark.parametrize("second_shot", ["same", "different"])[m
[32m+[m[32mdef test_his_yes_on_a_corrected_motion_redo_is_spent_on_the_resume([m
[32m+[m[32m    engine,[m
[32m+[m[32m    settings,[m
[32m+[m[32m    tmp_path,[m
[32m+[m[32m    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene[m
[32m+[m[32m    monkeypatch,[m
[32m+[m[32m    second_shot,[m
[32m+[m[32m):[m
[32m+[m[32m    storyboard_id = a_planned_film(engine, tmp_path, still_by="owner")[m
[32m+[m[32m    with Session(engine) as session, session.begin():[m
[32m+[m[32m        session.get(OwnerPolicy, 1).paid_media_approval = "EVERY_PAID_STEP"[m
[32m+[m[32m    account = Account(10_000)[m
[32m+[m[32m    spy = SpyVideo("seedance2_5", account)[m
[32m+[m[32m    models = Models(spy)[m
[32m+[m[32m    monkeypatch.setattr([m
[32m+[m[32m        stages,[m
[32m+[m[32m        "sheet_wiring",[m
[32m+[m[32m        lambda engine_, vault, settings_: {[m
[32m+[m[32m            "integration_id": None,[m
[32m+[m[32m            "capabilities": [SEEDANCE],[m
[32m+[m[32m            "image_adapter": None,[m
[32m+[m[32m            "account": account,[m
[32m+[m[32m            "adapter_for_model": models,[m
[32m+[m[32m            "resolution": "1080p",[m
[32m+[m[32m            "storage_root": tmp_path / "media",[m
[32m+[m[32m        },[m
[32m+[m[32m    )[m
[32m+[m[32m    asset_id = _failed_film(engine, tmp_path, storyboard_id)[m
[32m+[m[32m    reading = {[m
[32m+[m[32m        "storyboard_id": storyboard_id,[m
[32m+[m[32m        "media_asset_id": asset_id,[m
[32m+[m[32m        "report_id": str(uuid4()),[m
[32m+[m[32m        "proposals": [[m
[32m+[m[32m            SimpleNamespace([m
[32m+[m[32m                scene_index=1, redo="motion", reason="the clip barely moved", free=False[m
[32m+[m[32m            )[m
[32m+[m[32m        ],[m
[32m+[m[32m        "findings": [{"scene_index": 1, "text": "Scena 1: clipul aproape nu se mișcă"}],[m
[32m+[m[32m        "verdicts": [],[m
[32m+[m[32m    }[m
[32m+[m
[32m+[m[32m    # Walk 1: her brief, his rewrite, her review; the redo is asked on the corrected words.[m
[32m+[m[32m    first = _walk(engine, settings, agents_say(studio, Agents()), storyboard_id, reading)[m
[32m+[m
[32m+[m[32m    assert first["bought"] == [] and len(first["asked"]) == 1, first[m
[32m+[m[32m    assert len(_rewrites(engine, storyboard_id)) == 1[m
[32m+[m[32m    corrected = dict(scene(engine, storyboard_id).prompt_json)[m
[32m+[m[32m    approval_id = first["asked"][0]["approval_id"][m
[32m+[m[32m    with Session(engine) as session:[m
[32m+[m[32m        hash_asked = session.get(ApprovalRequest, approval_id).proposed_diff["plan_hash"][m
[32m+[m[32m    assert spy.asked == [][m
[32m+[m
[32m+[m[32m    # His yes; the walk resumes — with an editor who would say the same words, or others.[m
[32m+[m[32m    answer(engine, approval_id, "APPROVED", note="Da, reface mișcarea scenei 1.")[m
[32m+[m[32m    agents = Agents() if second_shot == "same" else Agents(shot=SHOT_V3)[m
[32m+[m[32m    second = _walk(engine, settings, agents_say(studio, agents), storyboard_id, reading)[m
[32m+[m
[32m+[m[32m    assert second["asked"] == [] and second["refused"] == [], second[m
[32m+[m[32m    assert [entry["scene_index"] for entry in second["bought"]] == [1], second[m
[32m+[m[32m    assert len(_rewrites(engine, storyboard_id)) == 1, "nothing was rewritten again"[m
[32m+[m[32m    assert len(events(engine, BRIEF_EVENT, storyboard_id)) == 1, "she was not asked again"[m
[32m+[m[32m    assert dict(scene(engine, storyboard_id).prompt_json) == corrected[m
[32m+[m[32m    with Session(engine) as session:[m
[32m+[m[32m        rows = list(session.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at)))[m
[32m+[m[32m        assert [row.proposed_diff.get("plan_hash") for row in rows] == [hash_asked][m
[32m+[m[32m        assert session.get(ApprovalRequest, approval_id).consumed_at is not None[m
[32m+[m[32m    # The clip was bought once, on the corrected words.[m
[32m+[m[32m    expected, _negative = motion_prompt_for(corrected, "seedance2_5", None)[m
[32m+[m[32m    (asked,) = spy.asked[m
[32m+[m[32m    assert asked["prompt"] == expected and "from left to right" in asked["prompt"][m
[32m+[m
[32m+[m
[32m+[m[32mdef test_only_her_briefs_rewrite_counts_as_the_correction(engine, tmp_path):[m
[32m+[m[32m    """The Codex review of c6dc05c: the serial's recomposition and its technical re-roll[m
[32m+[m[32m    write the same event as her brief's rewrite, with `decided_by: director`, on words that[m
[32m+[m[32m    may not have changed. Only the brief's rewrite (`REWRITE_REASON`), newer than the film[m
[32m+[m[32m    and than every take of the scene, is the correction his yes was asked on."""[m
[32m+[m[32m    storyboard_id = a_planned_film(engine, tmp_path, still_by="owner")[m
[32m+[m[32m    asset_id = _failed_film(engine, tmp_path, storyboard_id)[m
[32m+[m[32m    with Session(engine) as session, session.begin():[m
[32m+[m[32m        # The film and its takes well before any rewrite below.[m
[32m+[m[32m        session.get(MediaAsset, asset_id).created_at = "2026-10-01T00:00:00+00:00"[m
[32m+[m[32m        for take in session.scalars([m
[32m+[m[32m            select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)[m
[32m+[m[32m        ):[m
[32m+[m[32m            take.created_at = "2026-10-01T00:00:00+00:00"[m
[32m+[m
[32m+[m[32m    def rewritten(reason: str, layer: str = "motion") -> None:[m
[32m+[m[32m        with Session(engine) as session, session.begin():[m
[32m+[m[32m            append_event([m
[32m+[m[32m                session,[m
[32m+[m[32m                SCENE_PROMPTS_REWRITTEN_EVENT,[m
[32m+[m[32m                "storyboard",[m
[32m+[m[32m                storyboard_id,[m
[32m+[m[32m                1,[m
[32m+[m[32m                {[m
[32m+[m[32m                    "storyboard_id": storyboard_id,[m
[32m+[m[32m                    "scene_index": 1,[m
[32m+[m[32m                    "reason": reason,[m
[32m+[m[32m                    "decided_by": "director",[m
[32m+[m[32m                    "layer": layer,[m
[32m+[m[32m                },[m
[32m+[m[32m                str(uuid4()),[m
[32m+[m[32m            )[m
[32m+[m
[32m+[m[32m    def corrected() -> dict | None:[m
[32m+[m[32m        with Session(engine) as session:[m
[32m+[m[32m            return stages._corrected_for_film(session, storyboard_id, 1, asset_id)[m
[32m+[m
[32m+[m[32m    assert corrected() is None, "nothing corrected yet"[m
[32m+[m[32m    rewritten(SERIAL_RECOMPOSE_REASON, layer="still")[m
[32m+[m[32m    assert corrected() is None, "a recomposition is not her brief's correction"[m
[32m+[m[32m    rewritten(REWRITE_REASON)[m
[32m+[m[32m    found = corrected()[m
[32m+[m[32m    assert found is not None and found["layer"] == "motion"[m
[32m+[m[32m    # A take bought on the correction since: the words are spent, nothing to resume.[m
[32m+[m[32m    with Session(engine) as session, session.begin():[m
[32m+[m[32m        take = session.scalar(select(SceneTake).where(SceneTake.storyboard_id == storyboard_id))[m
[32m+[m[32m        take.created_at = utc_now()[m
[32m+[m[32m    assert corrected() is None[m
[1mdiff --git a/tests/test_rewritten_motion_reaches_the_model.py b/tests/test_rewritten_motion_reaches_the_model.py[m
[1mnew file mode 100644[m
[1mindex 0000000..5975b7d[m
[1m--- /dev/null[m
[1m+++ b/tests/test_rewritten_motion_reaches_the_model.py[m
[36m@@ -0,0 +1,165 @@[m
[32m+[m[32m"""The motion prompt the Director's ladder rewrote is the one the video model is sent, on the[m
[32m+[m[32mtest-shot step and on the motion step (2026-10-13, the Owner: «la fel și la video, aceeași[m
[32m+[m[32mlogică; promptul trebuie schimbat»).[m
[32m+[m
[32m+[m[32mOffline, with faked vendors and scripted agents: after a motion-layer rewrite the hold on the[m
[32m+[m[32mrefused scene is lifted and the request handed to the video vendor is exactly the rendering of[m
[32m+[m[32mthe rewritten package (`prompt_agent.motion_prompt_for`), never the old words."""[m
[32m+[m
[32m+[m[32mfrom __future__ import annotations[m
[32m+[m
[32m+[m[32mfrom uuid import uuid4[m
[32m+[m
[32m+[m[32mimport pytest[m
[32m+[m[32mfrom app.media.assembler import MOTION_HOLD_EVENT, decide_take, motion_plan[m
[32m+[m[32mfrom app.media.models import SceneTake, StoryboardScene[m
[32m+[m[32mfrom app.media.prompt_agent import motion_prompt_for[m
[32m+[m[32mfrom app.media.scene_rewrite import MOTION, rewrite_failed_scene[m
[32m+[m[32mfrom app.media.toolchain import find_ffmpeg[m
[32m+[m[32mfrom sqlalchemy import select[m
[32m+[m[32mfrom sqlalchemy.orm import Session[m
[32m+[m[32mfrom test_clip_qc_wiring import ScriptedCheck, events, shots[m
[32m+[m[32mfrom test_director_rewrites_failed_scene import (  # noqa: F401 - the studio fixture[m
[32m+[m[32m    PLAN,[m
[32m+[m[32m    SHOT,[m
[32m+[m[32m    Agents,[m
[32m+[m[32m    a_planned_film,[m
[32m+[m[32m    agents_say,[m
[32m+[m[32m    refused_twice,[m
[32m+[m[32m    scene,[m
[32m+[m[32m    studio,[m
[32m+[m[32m)[m
[32m+[m[32mfrom test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film, approved[m
[32m+[m
[32m+[m[32mpytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_test_shot_is_bought_on_the_rewritten_motion_prompt([m
[32m+[m[32m    engine,[m
[32m+[m[32m    tmp_path,[m
[32m+[m[32m    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene[m
[32m+[m[32m):[m
[32m+[m[32m    storyboard_id = a_planned_film(engine, tmp_path)[m
[32m+[m[32m    models, account, spy = refused_twice(engine, storyboard_id, tmp_path)[m
[32m+[m[32m    before = scene(engine, storyboard_id)[m
[32m+[m
[32m+[m[32m    outcome = rewrite_failed_scene([m
[32m+[m[32m        engine, agents_say(studio, Agents()), storyboard_id, 1, str(uuid4())[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m[32m    assert outcome["rewritten"] is True and outcome["layer"] == MOTION, outcome[m
[32m+[m[32m    after = scene(engine, storyboard_id)[m
[32m+[m[32m    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["test_shot"][m
[32m+[m[32m    assert plan["held"] == [] and plan["to_buy"] == [1][m
[32m+[m[32m    summary = approved([m
[32m+[m[32m        engine,[m
[32m+[m[32m        storyboard_id,[m
[32m+[m[32m        tmp_path,[m
[32m+[m[32m        "test_shot",[m
[32m+[m[32m        models,[m
[32m+[m[32m        account,[m
[32m+[m[32m        clip_check=ScriptedCheck("PASSED"),[m
[32m+[m[32m    )[m
[32m+[m[32m    (entry,) = summary["scenes"][m
[32m+[m[32m    assert entry["status"] == "PAID"[m
[32m+[m[32m    expected, _negative = motion_prompt_for(after.prompt_json, "seedance2_5", None)[m
[32m+[m[32m    old, _negative = motion_prompt_for(before.prompt_json, "seedance2_5", None)[m
[32m+[m[32m    assert spy.asked[0]["prompt"] == old[m
[32m+[m[32m    assert spy.asked[-1]["prompt"] == expected[m
[32m+[m[32m    assert "from left to right" in expected and "from left to right" not in old[m
[32m+[m
[32m+[m
[32m+[m[32mdef _scene(engine, storyboard_id: str, index: int) -> StoryboardScene:[m
[32m+[m[32m    with Session(engine) as session:[m
[32m+[m[32m        row = session.scalar([m
[32m+[m[32m            select(StoryboardScene).where([m
[32m+[m[32m                StoryboardScene.storyboard_id == storyboard_id,[m
[32m+[m[32m                StoryboardScene.scene_index == index,[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
[32m+[m[32m        session.expunge(row)[m
[32m+[m[32m        return row[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_motion_step_is_bought_on_the_rewritten_motion_prompt([m
[32m+[m[32m    engine,[m
[32m+[m[32m    tmp_path,[m
[32m+[m[32m    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene[m
[32m+[m[32m):[m
[32m+[m[32m    storyboard_id = a_film(engine, tmp_path, scenes=2)[m
[32m+[m[32m    with Session(engine) as session, session.begin():[m
[32m+[m[32m        for row in session.scalars([m
[32m+[m[32m            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)[m
[32m+[m[32m        ):[m
[32m+[m[32m            row.prompt_json = {**dict(row.prompt_json or {}), **PLAN}[m
[32m+[m[32m        for take in session.scalars([m
[32m+[m[32m            select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)[m
[32m+[m[32m        ):[m
[32m+[m[32m            take.approved_by = "owner"[m
[32m+[m[32m    account = Account(10_000)[m
[32m+[m[32m    spy = SpyVideo("seedance2_5", account)[m
[32m+[m[32m    models = Models(spy)[m
[32m+[m[32m    # The hero (scene 1) passes and the Owner approves it.[m
[32m+[m[32m    approved([m
[32m+[m[32m        engine,[m
[32m+[m[32m        storyboard_id,[m
[32m+[m[32m        tmp_path,[m
[32m+[m[32m        "test_shot",[m
[32m+[m[32m        models,[m
[32m+[m[32m        account,[m
[32m+[m[32m        clip_check=ScriptedCheck("PASSED"),[m
[32m+[m[32m    )[m
[32m+[m[32m    (hero,) = [t for t in shots(engine, storyboard_id) if t.status == "PAID"][m
[32m+[m[32m    decide_take(engine, hero.id, "APPROVED", decided_by="owner")[m
[32m+[m[32m    # The motion step: scene 2's clip fails clip QC, and its retry too — the scene is held.[m
[32m+[m[32m    approved([m
[32m+[m[32m        engine,[m
[32m+[m[32m        storyboard_id,[m
[32m+[m[32m        tmp_path,[m
[32m+[m[32m        "motion",[m
[32m+[m[32m        models,[m
[32m+[m[32m        account,[m
[32m+[m[32m        clip_check=ScriptedCheck("FAILED"),[m
[32m+[m[32m    )[m
[32m+[m[32m    assert {t.status for t in shots(engine, storyboard_id) if t.scene_number == 2} == {"REJECTED"}[m
[32m+[m[32m    held = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["motion"][m
[32m+[m[32m    assert held["held"] == [2] and held["to_buy"] == [], held[m
[32m+[m[32m    assert [[m
[32m+[m[32m        e.payload["scene_number"] for e in events(engine, MOTION_HOLD_EVENT, storyboard_id)[m
[32m+[m[32m    ] == [2][m
[32m+[m[32m    posts_before = models.posts()[m
[32m+[m[32m    old_sent = spy.asked[-1]["prompt"][m
[32m+[m[32m    before = _scene(engine, storyboard_id, 2)[m
[32m+[m
[32m+[m[32m    outcome = rewrite_failed_scene([m
[32m+[m[32m        engine,[m
[32m+[m[32m        agents_say(studio, Agents(shot={**SHOT, "scene_index": 2})),[m
[32m+[m[32m        storyboard_id,[m
[32m+[m[32m        2,[m
[32m+[m[32m        str(uuid4()),[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m[32m    assert outcome["rewritten"] is True and outcome["layer"] == MOTION, outcome[m
[32m+[m[32m    after = _scene(engine, storyboard_id, 2)[m
[32m+[m[32m    assert after.prompt_json["camera_move"] == "slow pan right"[m
[32m+[m[32m    assert after.prompt_json["motion_intent"] != before.prompt_json["motion_intent"][m
[32m+[m[32m    lifted = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["motion"][m
[32m+[m[32m    assert lifted["held"] == [] and lifted["to_buy"] == [2], lifted[m
[32m+[m
[32m+[m[32m    summary = approved([m
[32m+[m[32m        engine,[m
[32m+[m[32m        storyboard_id,[m
[32m+[m[32m        tmp_path,[m
[32m+[m[32m        "motion",[m
[32m+[m[32m        models,[m
[32m+[m[32m        account,[m
[32m+[m[32m        clip_check=ScriptedCheck("PASSED"),[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m[32m    assert models.posts() == posts_before + 1[m
[32m+[m[32m    by_scene = {e["scene_index"]: e for e in summary["scenes"]}[m
[32m+[m[32m    assert by_scene[2]["status"] == "PAID", by_scene[m
[32m+[m[32m    expected, _negative = motion_prompt_for(after.prompt_json, "seedance2_5", None)[m
[32m+[m[32m    sent = spy.asked[-1]["prompt"][m
[32m+[m[32m    assert sent == expected and sent != old_sent[m
[32m+[m[32m    assert "from left to right" in sent and "from left to right" not in old_sent[m
[1mdiff --git a/tests/test_rewritten_still_reaches_the_model.py b/tests/test_rewritten_still_reaches_the_model.py[m
[1mnew file mode 100644[m
[1mindex 0000000..03f0842[m
[1m--- /dev/null[m
[1m+++ b/tests/test_rewritten_still_reaches_the_model.py[m
[36m@@ -0,0 +1,177 @@[m
[32m+[m[32m"""The still prompt the Director's ladder rewrote is the one the image model is sent[m
[32m+[m[32m(2026-10-13, the Owner: «noua imagine ar trebui refăcută cu noul prompt»).[m
[32m+[m
[32m+[m[32mOffline, with faked vendors and scripted agents. After a still-layer rewrite the stills plan[m
[32m+[m[32mnames the new words, the scene is to be bought (not held), and the request handed to the image[m
[32m+[m[32mvendor begins with them; a scene the gate held for the Owner is bought again, on the ladder's[m
[32m+[m[32mnew words, once her ladder rewrote it. Nothing here proves a live vendor."""[m
[32m+[m
[32m+[m[32mfrom __future__ import annotations[m
[32m+[m
[32m+[m[32mfrom uuid import uuid4[m
[32m+[m
[32m+[m[32mimport pytest[m
[32m+[m[32mfrom app.media.models import StoryboardScene[m
[32m+[m[32mfrom app.media.prompt_lint import still_motion[m
[32m+[m[32mfrom app.media.scene_rewrite import STILL, rewrite_failed_scene[m
[32m+[m[32mfrom app.media.stills_stage import stills_plan[m
[32m+[m[32mfrom app.media.toolchain import find_ffmpeg[m
[32m+[m[32mfrom sqlalchemy import select[m
[32m+[m[32mfrom sqlalchemy.orm import Session[m
[32m+[m[32mfrom test_clip_qc_wiring import ScriptedCheck[m
[32m+[m[32mfrom test_director_rewrites_failed_scene import (  # noqa: F401 - the studio fixture[m
[32m+[m[32m    BRIEF,[m
[32m+[m[32m    PLAN,[m
[32m+[m[32m    STILL_SHOT,[m
[32m+[m[32m    Agents,[m
[32m+[m[32m    a_planned_film,[m
[32m+[m[32m    agents_say,[m
[32m+[m[32m    refused_twice,[m
[32m+[m[32m    scene,[m
[32m+[m[32m    studio,[m
[32m+[m[32m)[m
[32m+[m[32mfrom test_film_costing import approved[m
[32m+[m[32mfrom test_fix_is_verified import fix, verdict[m
[32m+[m[32mfrom test_stills_stage import ([m
[32m+[m[32m    FACE,[m
[32m+[m[32m    NO_FACE,[m
[32m+[m[32m    SUBJECTS,[m
[32m+[m[32m    SpyJudge,[m
[32m+[m[32m    SpyStills,[m
[32m+[m[32m    a_film,[m
[32m+[m[32m    approved_run,[m
[32m+[m[32m    takes,[m
[32m+[m[32m)[m
[32m+[m
[32m+[m[32mpytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")[m
[32m+[m
[32m+[m
[32m+[m[32mdef _words(text: str) -> str:[m
[32m+[m[32m    return " ".join(text.split())[m
[32m+[m
[32m+[m
[32m+[m[32mclass AnsweringJudge:[m
[32m+[m[32m    """The vision model, faked: the still is right, and every mistake the words were[m
[32m+[m[32m    rewritten to correct (`StillPlan.must_fix`) is gone from it."""[m
[32m+[m
[32m+[m[32m    def __init__(self):[m
[32m+[m[32m        self.looked_at: list[str] = [][m
[32m+[m
[32m+[m[32m    def __call__(self, engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):[m
[32m+[m[32m        self.looked_at.append(str(path))[m
[32m+[m[32m        gone = [fix(n, "gone", "the scene as rewritten") for n in range(1, len(plan.must_fix) + 1)][m
[32m+[m[32m        return verdict(plan.scene, fixes=gone)[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_after_a_still_rewrite_the_stills_step_buys_the_new_words([m
[32m+[m[32m    engine,[m
[32m+[m[32m    tmp_path,[m
[32m+[m[32m    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene[m
[32m+[m[32m):[m
[32m+[m[32m    storyboard_id = a_planned_film(engine, tmp_path, still_by="still_gate")[m
[32m+[m[32m    models, account, _spy = refused_twice(engine, storyboard_id, tmp_path)[m
[32m+[m[32m    first = rewrite_failed_scene([m
[32m+[m[32m        engine, agents_say(studio, Agents()), storyboard_id, 1, str(uuid4())[m
[32m+[m[32m    )[m
[32m+[m[32m    assert first["rewritten"] is True[m
[32m+[m[32m    # The movement, rewritten once, fails again: the picture's turn.[m
[32m+[m[32m    approved([m
[32m+[m[32m        engine,[m
[32m+[m[32m        storyboard_id,[m
[32m+[m[32m        tmp_path,[m
[32m+[m[32m        "test_shot",[m
[32m+[m[32m        models,[m
[32m+[m[32m        account,[m
[32m+[m[32m        clip_check=ScriptedCheck("FAILED"),[m
[32m+[m[32m    )[m
[32m+[m[32m    before = scene(engine, storyboard_id)[m
[32m+[m[32m    agents = Agents(brief={**BRIEF, "layer": "still"}, shot=STILL_SHOT)[m
[32m+[m
[32m+[m[32m    outcome = rewrite_failed_scene([m
[32m+[m[32m        engine, agents_say(studio, agents), storyboard_id, 1, str(uuid4())[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m[32m    assert outcome["rewritten"] is True and outcome["layer"] == STILL, outcome[m
[32m+[m[32m    after = scene(engine, storyboard_id)[m
[32m+[m[32m    assert after.visual_prompt != before.visual_prompt[m
[32m+[m[32m    assert "terraced rice fields" in after.visual_prompt.lower()[m
[32m+[m[32m    plan = stills_plan(engine, storyboard_id)[m
[32m+[m[32m    (row,) = plan["scenes"][m
[32m+[m[32m    assert row["still_prompt"] == _words(after.visual_prompt)[m
[32m+[m[32m    assert plan["to_buy"] == [1] and plan["held"] == [], (plan["to_buy"], plan["held"], row)[m
[32m+[m
[32m+[m[32m    images = SpyStills(balance=1_000)[m
[32m+[m[32m    result = approved_run(engine, storyboard_id, tmp_path, images, AnsweringJudge())[m
[32m+[m
[32m+[m[32m    (asked,) = images.asked[m
[32m+[m[32m    assert asked["prompt"].startswith(_words(after.visual_prompt))[m
[32m+[m[32m    assert "terraced rice fields" in asked["prompt"].lower()[m
[32m+[m[32m    assert _words(before.visual_prompt) not in asked["prompt"][m
[32m+[m[32m    # And the picture's words carry no movement (2026-10-13).[m
[32m+[m[32m    assert still_motion(asked["prompt"]) == ""[m
[32m+[m[32m    entry = next(e for e in result["scenes"] if e["scene_index"] == 1)[m
[32m+[m[32m    assert entry["status"] == "APPROVED", entry[m
[32m+[m
[32m+[m
[32m+[m[32mdef _plan_scene(engine, storyboard_id: str, index: int) -> None:[m
[32m+[m[32m    with Session(engine) as session, session.begin():[m
[32m+[m[32m        row = session.scalar([m
[32m+[m[32m            select(StoryboardScene).where([m
[32m+[m[32m                StoryboardScene.storyboard_id == storyboard_id,[m
[32m+[m[32m                StoryboardScene.scene_index == index,[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
[32m+[m[32m        row.prompt_json = {**dict(row.prompt_json or {}), **PLAN, "scene_index": index}[m
[32m+[m
[32m+[m
[32m+[m[32mdef _scene(engine, storyboard_id: str, index: int) -> StoryboardScene:[m
[32m+[m[32m    with Session(engine) as session:[m
[32m+[m[32m        row = session.scalar([m
[32m+[m[32m            select(StoryboardScene).where([m
[32m+[m[32m                StoryboardScene.storyboard_id == storyboard_id,[m
[32m+[m[32m                StoryboardScene.scene_index == index,[m
[32m+[m[32m            )[m
[32m+[m[32m        )[m
[32m+[m[32m        session.expunge(row)[m
[32m+[m[32m        return row[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_a_scene_the_gate_held_is_bought_again_once_her_ladder_rewrote_it([m
[32m+[m[32m    engine,[m
[32m+[m[32m    tmp_path,[m
[32m+[m[32m    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene[m
[32m+[m[32m):[m
[32m+[m[32m    storyboard_id = a_film(engine, tmp_path)[m
[32m+[m[32m    for index in SUBJECTS:[m
[32m+[m[32m        _plan_scene(engine, storyboard_id, index)[m
[32m+[m
[32m+[m[32m    def faces_in_two(prompt, call):[m
[32m+[m[32m        return [FACE, FACE] if SUBJECTS[2] in prompt else list(NO_FACE)[m
[32m+[m
[32m+[m[32m    approved_run(engine, storyboard_id, tmp_path, SpyStills(pictures=faces_in_two), SpyJudge())[m
[32m+[m[32m    plan = stills_plan(engine, storyboard_id)[m
[32m+[m[32m    assert plan["held"] == [2] and plan["to_buy"] == [][m
[32m+[m[32m    before = _scene(engine, storyboard_id, 2)[m
[32m+[m[32m    agents = Agents(brief={**BRIEF, "layer": "still"}, shot={**STILL_SHOT, "scene_index": 2})[m
[32m+[m
[32m+[m[32m    outcome = rewrite_failed_scene([m
[32m+[m[32m        engine, agents_say(studio, agents), storyboard_id, 2, str(uuid4())[m
[32m+[m[32m    )[m
[32m+[m
[32m+[m[32m    assert outcome["rewritten"] is True and outcome["layer"] == STILL, outcome[m
[32m+[m[32m    after = _scene(engine, storyboard_id, 2)[m
[32m+[m[32m    assert after.visual_prompt != before.visual_prompt[m
[32m+[m[32m    plan = stills_plan(engine, storyboard_id)[m
[32m+[m[32m    (row,) = [entry for entry in plan["scenes"] if entry["scene_index"] == 2][m
[32m+[m[32m    assert row["still_prompt"] == _words(after.visual_prompt)[m
[32m+[m[32m    assert plan["to_buy"] == [2] and plan["held"] == [][m
[32m+[m
[32m+[m[32m    images = SpyStills(balance=1_000)[m
[32m+[m[32m    result = approved_run(engine, storyboard_id, tmp_path, images, AnsweringJudge())[m
[32m+[m
[32m+[m[32m    (sent,) = [asked["prompt"] for asked in images.asked][m
[32m+[m[32m    assert sent.startswith(_words(after.visual_prompt))[m
[32m+[m[32m    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)[m
[32m+[m[32m    assert entry["status"] == "APPROVED", entry[m
[32m+[m[32m    bought = [t for t in takes(engine, storyboard_id) if t.scene_number == 2][m
[32m+[m[32m    assert len({t.prompt_hash for t in bought}) == 2, "the new words are a new take identity"[m
[1mdiff --git a/tests/test_still_prompt_is_static.py b/tests/test_still_prompt_is_static.py[m
[1mnew file mode 100644[m
[1mindex 0000000..7e9ecfa[m
[1m--- /dev/null[m
[1m+++ b/tests/test_still_prompt_is_static.py[m
[36m@@ -0,0 +1,153 @@[m
[32m+[m[32m"""The still prompt is one frozen moment (the Owner, 2026-10-13: «în promptul de imagine nu[m
[32m+[m[32mare ce să caute indicații de mișcare»).[m
[32m+[m
[32m+[m[32mOffline, no provider: the compiler alone. A clause of the plan that moves the camera leaves[m
[32m+[m[32mthe still (a clause that only moves it is the motion's; one that says a moment first keeps the[m
[32m+[m[32mmoment), a tempo or a span of the clip leaves its clause, and the motion prompt keeps all of[m
[32m+[m[32mit. The lint says when a stored still prompt still carries one, and the writers are told."""[m
[32m+[m
[32m+[m[32mfrom __future__ import annotations[m
[32m+[m
[32m+[m[32mimport pytest[m
[32m+[m[32mfrom app.media.prompt_agent import ([m
[32m+[m[32m    _SHOTS_INSTRUCTIONS,[m
[32m+[m[32m    COMPOSITION_SENTENCE,[m
[32m+[m[32m    NO_PEOPLE_SENTENCE,[m
[32m+[m[32m    PEOPLE_SENTENCE,[m
[32m+[m[32m    compile_prompts,[m
[32m+[m[32m)[m
[32m+[m[32mfrom app.media.prompt_lint import ([m
[32m+[m[32m    WARN,[m
[32m+[m[32m    has_block,[m
[32m+[m[32m    lint_still_prompt,[m
[32m+[m[32m    static_clause,[m
[32m+[m[32m    still_motion,[m
[32m+[m[32m    without_tempo,[m
[32m+[m[32m)[m
[32m+[m[32mfrom app.media.scene_rewrite import _REWRITE_INSTRUCTIONS[m
[32m+[m
[32m+[m[32mVILLAGE = {[m
[32m+[m[32m    "scene_index": 1,[m
[32m+[m[32m    "scene_kind": "LIVE",[m
[32m+[m[32m    "subject": "a far village of stone houses on a terraced slope",[m
[32m+[m[32m    "action": "thick grey cloud rolls steadily across the ridges from left to right",[m
[32m+[m[32m    "environment": "steep Himalayan ridges under low cloud",[m
[32m+[m[32m    "camera": "wide establishing shot, 24mm lens",[m
[32m+[m[32m    "lighting": "soft overcast daylight",[m
[32m+[m[32m    "motion": "thick grey cloud rolls steadily across the ridges from left to right",[m
[32m+[m[32m    "camera_move": "slow pan right",[m
[32m+[m[32m}[m
[32m+[m[32mTHERMOMETER = {[m
[32m+[m[32m    "scene_index": 2,[m
[32m+[m[32m    "scene_kind": "LIVE",[m
[32m+[m[32m    "subject": "a mercury thermometer on a lab bench",[m
[32m+[m[32m    "action": "the mercury rises slowly as the camera pushes in on the Celsius scale",[m
[32m+[m[32m    "environment": "a dim laboratory, steam drifting slowly",[m
[32m+[m[32m    "camera": "detail shot, 85mm lens, slow push-in",[m
[32m+[m[32m    "lighting": "one cold lamp",[m
[32m+[m[32m    "motion": "the mercury climbs steadily over the clip",[m
[32m+[m[32m    "camera_move": "slow push-in",[m
[32m+[m[32m}[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_still_keeps_the_moment_and_leaves_the_tempo_to_the_motion():[m
[32m+[m[32m    compiled = compile_prompts(VILLAGE, {})[m
[32m+[m
[32m+[m[32m    still, motion = compiled["still_prompt"], compiled["motion_prompt"][m
[32m+[m[32m    assert "Thick grey cloud rolls across the ridges from left to right." in still[m
[32m+[m[32m    assert "steadily" not in still and "pan" not in still.lower()[m
[32m+[m[32m    assert "rolls steadily across the ridges" in motion and "Slow pan right" in motion[m
[32m+[m[32m    assert still_motion(still) == ""[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_a_clause_that_moves_the_camera_leaves_the_still_and_the_moment_stays():[m
[32m+[m[32m    compiled = compile_prompts(THERMOMETER, {})[m
[32m+[m
[32m+[m[32m    still, motion = compiled["still_prompt"], compiled["motion_prompt"][m
[32m+[m[32m    assert "The mercury rises." in still[m
[32m+[m[32m    assert "camera" not in still.lower() and "push" not in still.lower()[m
[32m+[m[32m    assert "slowly" not in still and "steadily" not in still and "over the clip" not in still[m
[32m+[m[32m    assert "steam drifting" in still[m
[32m+[m[32m    assert still_motion(still) == ""[m
[32m+[m[32m    assert "Slow push-in" in motion and "climbs steadily over the clip" in motion[m
[32m+[m[32m    assert not has_block(lint_still_prompt(still, scene=2))[m
[32m+[m[32m    assert "STILL_MOTION" not in {f.code for f in lint_still_prompt(still, scene=2)}[m
[32m+[m
[32m+[m
[32m+[m[32m@pytest.mark.parametrize([m
[32m+[m[32m    ("clause", "static"),[m
[32m+[m[32m    [[m
[32m+[m[32m        ([m
[32m+[m[32m            "the mercury rises slowly as the camera pushes in on the Celsius scale",[m
[32m+[m[32m            "the mercury rises slowly",[m
[32m+[m[32m        ),[m
[32m+[m[32m        ("the camera pushes in on the scale", ""),[m
[32m+[m[32m        ("a slow pan right across the valley", ""),[m
[32m+[m[32m        ("wind bends the young rice in long waves", "wind bends the young rice in long waves"),[m
[32m+[m[32m        ("a static camera on the empty hall", "a static camera on the empty hall"),[m
[32m+[m[32m        ("the ledger open on the desk, the camera drifting closer", "the ledger open on the desk"),[m
[32m+[m[32m        # The subject's own moment, in words the cinema also uses (the Codex review of[m
[32m+[m[32m        # c6dc05c): a bare «orbits» or «pulls back» moves no camera.[m
[32m+[m[32m        ("Earth orbits the Sun", "Earth orbits the Sun"),[m
[32m+[m[32m        ("she pulls back the curtain", "she pulls back the curtain"),[m
[32m+[m[32m        ("the view orbits the tower", ""),[m
[32m+[m[32m        ("a dolly in toward the ledger", ""),[m
[32m+[m[32m        ("the hall, tracking left along the benches", "the hall"),[m
[32m+[m[32m    ],[m
[32m+[m[32m)[m
[32m+[m[32mdef test_the_camera_leaves_a_still_clause(clause, static):[m
[32m+[m[32m    assert static_clause(clause) == static[m
[32m+[m
[32m+[m
[32m+[m[32m@pytest.mark.parametrize([m
[32m+[m[32m    ("said", "kept"),[m
[32m+[m[32m    [[m
[32m+[m[32m        ("cloud rolls steadily across the ridges", "cloud rolls across the ridges"),[m
[32m+[m[32m        ("the mercury rises slowly, then holds", "the mercury rises, then holds"),[m
[32m+[m[32m        ("dust rises over the clip's seconds", "dust rises"),[m
[32m+[m[32m        ("a quiet valley at dawn", "a quiet valley at dawn"),[m
[32m+[m[32m    ],[m
[32m+[m[32m)[m
[32m+[m[32mdef test_the_tempo_leaves_a_still_clause(said, kept):[m
[32m+[m[32m    assert without_tempo(said) == kept[m
[32m+[m
[32m+[m
[32m+[m[32m@pytest.mark.parametrize([m
[32m+[m[32m    ("prompt", "evidence"),[m
[32m+[m[32m    [[m
[32m+[m[32m        ("Wide shot. The camera slowly pushes in on the thermometer.", "The camera slowly pushes"),[m
[32m+[m[32m        ("A valley at dawn, a slow pan right across the ridges.", "slow pan right"),[m
[32m+[m[32m        ("Cloud rolls steadily across the ridges.", "steadily"),[m
[32m+[m[32m        ("Dust rises over the clip's seconds.", "over the clip's seconds"),[m
[32m+[m[32m    ],[m
[32m+[m[32m)[m
[32m+[m[32mdef test_the_lint_warns_about_a_still_prompt_that_moves(prompt, evidence):[m
[32m+[m[32m    (finding,) = [f for f in lint_still_prompt(prompt, scene=1) if f.code == "STILL_MOTION"][m
[32m+[m[32m    assert finding.severity == WARN and finding.evidence == evidence[m
[32m+[m[32m    assert "un singur moment nemișcat" in finding.message_ro[m
[32m+[m
[32m+[m
[32m+[m[32m@pytest.mark.parametrize([m
[32m+[m[32m    "prompt",[m
[32m+[m[32m    [[m
[32m+[m[32m        "A quiet valley at dawn, mist in the hollows, a village far below.",[m
[32m+[m[32m        "A static camera on the empty hall, handheld grain, one cold lamp.",[m
[32m+[m[32m        # The compiler's own sentences (2026-10-13: «the frame holds» was read as a move).[m
[32m+[m[32m        NO_PEOPLE_SENTENCE,[m
[32m+[m[32m        PEOPLE_SENTENCE,[m
[32m+[m[32m        COMPOSITION_SENTENCE,[m
[32m+[m[32m        "The shot shows the ledger open on the desk; the camera stays on it.",[m
[32m+[m[32m        "Earth orbits the Sun, its night side dark; she pulls back the curtain.",[m
[32m+[m[32m    ],[m
[32m+[m[32m)[m
[32m+[m[32mdef test_a_still_that_stands_still_is_not_flagged(prompt):[m
[32m+[m[32m    assert still_motion(prompt) == ""[m
[32m+[m[32m    assert "STILL_MOTION" not in {f.code for f in lint_still_prompt(prompt, scene=1)}[m
[32m+[m
[32m+[m
[32m+[m[32mdef test_the_writers_are_told_the_still_is_one_frozen_moment():[m
[32m+[m[32m    assert "one frozen moment" in _REWRITE_INSTRUCTIONS[m
[32m+[m[32m    assert "everything that moves goes to motion, camera_move and ending_frame" in ([m
[32m+[m[32m        _REWRITE_INSTRUCTIONS[m
[32m+[m[32m    )[m
[32m+[m[32m    assert "never a camera move, a speed or a span of the clip's seconds" in _SHOTS_INSTRUCTIONS[m
