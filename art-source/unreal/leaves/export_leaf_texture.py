"""
Unreal Engine 5.8 commandlet, step 1 of 3 of the street trees' green leaves: exports Soul: City's leaf
texture T_Foliage_Leaves_D (diffuse + alpha, autumn orange: its leaves average RGB 102, 75, 43) to
leaves/generated/T_Foliage_Leaves_D.png. The generated folder is ignored by Git (pack content).

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=leaves/export_leaf_texture.py
  py -3.11 leaves/green_leaves.py leaves/generated/T_Foliage_Leaves_D.png leaves/generated/T_HQ_Leaves_Green.png
  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=leaves/import_green_leaves.py
"""

import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
GENERATED = os.path.join(HERE, "generated")
TEXTURE = "/Game/SoulCity/Environment/Textures/Foliage/T_Foliage_Leaves_D"
OUT = os.path.join(GENERATED, "T_Foliage_Leaves_D.png")

os.makedirs(GENERATED, exist_ok=True)
tex = unreal.load_asset(TEXTURE)
if tex is None:
    unreal.log_error(f"AMN_LEAF texture not found: {TEXTURE}")
else:
    task = unreal.AssetExportTask()
    task.object = tex
    task.filename = OUT
    task.automated = True
    task.prompt = False
    task.replace_identical = True
    task.exporter = unreal.TextureExporterPNG()
    ok = unreal.Exporter.run_asset_export_task(task)
    unreal.log(f"AMN_LEAF exported {TEXTURE} ({tex.blueprint_get_size_x()}x{tex.blueprint_get_size_y()}) -> {OUT}: {ok}")
