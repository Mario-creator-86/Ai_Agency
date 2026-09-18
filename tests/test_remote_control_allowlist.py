"""The live game's Remote Control allow-list (art-source/unreal/AMNReference/Config/
DefaultRemoteControl.ini) names every function the backend may call, and nothing broader.

An entry written without its FunctionName, or with it outside the parentheses the TOptional needs,
fails to import and then allows every function of its class; bAllowAnyRemoteFunctionCall=True
would allow everything. Either would open the live game to any call, so the file is pinned here to
exactly the people pass's three calls, the environment pass's ten (the real-sky phase's
corrected specification) and the clock's one read of the game time, each in the one form that
imports.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INI = ROOT / "art-source" / "unreal" / "AMNReference" / "Config" / "DefaultRemoteControl.ini"
ENTRY = re.compile(
    r'^\+CustomAllowedRemoteFunctionCalls=\(ClassPath="/Script/Engine\.(\w+)",'
    r'FunctionName=\("(\w+)"\),bAllowChildClasses=(True|False)\)$'
)

PEOPLE = {
    ("Actor", "SetActorHiddenInGame"),
    ("SkeletalMeshComponent", "SetPlayRate"),
    ("SkeletalMeshComponent", "SetPosition"),
}
ENVIRONMENT = {
    ("LightComponent", "SetIntensity"),
    ("LightComponent", "SetLightColor"),
    ("SceneComponent", "K2_SetWorldRotation"),
    ("SkyLightComponent", "SetIntensity"),
    ("SkyLightComponent", "SetLightColor"),
    ("SkyLightComponent", "SetLowerHemisphereColor"),
    ("ExponentialHeightFogComponent", "SetFogInscatteringColor"),
    ("ExponentialHeightFogComponent", "SetFogDensity"),
    ("MeshComponent", "SetScalarParameterValueOnMaterials"),
    ("MeshComponent", "SetVectorParameterValueOnMaterials"),
}
# The clock's one read: the game time its material's Time node shows, which ClockOffsetS is
# computed against (backend/app/office/unreal.py CLOCK_TIME_READ). A getter on a static library,
# with child classes refused: nothing but this one function of this one class.
CLOCK_READ = {("GameplayStatics", "GetTimeSeconds")}


def lines():
    return [
        ln.strip()
        for ln in INI.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(";")
    ]


def test_no_call_is_allowed_by_default():
    assert "bAllowAnyRemoteFunctionCall=False" in lines()
    assert not any(ln.lower().startswith("ballowanyremotefunctioncall=true") for ln in lines())


def test_every_entry_names_one_function_in_the_form_that_imports():
    entries = [ln for ln in lines() if "CustomAllowedRemoteFunctionCalls" in ln]
    assert entries
    for ln in entries:
        assert ENTRY.match(ln), ln


def entries():
    found = [ENTRY.match(ln) for ln in lines() if "CustomAllowedRemoteFunctionCalls" in ln]
    assert all(found), "an entry is not in the form that imports"
    return [m.groups() for m in found if m]


def test_exactly_the_people_the_environment_and_the_clock_read():
    found = [(cls, fn) for cls, fn, _ in entries()]
    assert len(found) == len(set(found))
    assert set(found) == PEOPLE | ENVIRONMENT | CLOCK_READ


def test_child_classes_are_allowed_for_the_setters_and_refused_for_the_clock_read():
    for cls, fn, children in entries():
        expected = "False" if (cls, fn) in CLOCK_READ else "True"
        assert children == expected, (cls, fn, children)


def test_the_clock_read_is_the_one_the_backend_makes():
    from app.office.unreal import CLOCK_TIME_READ, ENVIRONMENT_CALLS

    target, function = CLOCK_TIME_READ
    assert target == "/Script/Engine.Default__GameplayStatics"
    assert {("GameplayStatics", function)} == CLOCK_READ
    assert set(ENVIRONMENT_CALLS) == ENVIRONMENT


def test_the_http_server_stays_on_this_machine():
    ls = lines()
    assert "RemoteControlHttpServerPort=30010" in ls
    assert "bAutoStartWebSocketServer=False" in ls
    assert "RemoteControlWebsocketServerBindAddress=127.0.0.1" in ls
