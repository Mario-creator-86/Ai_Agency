"""ActorCore Sample Motions retargeted onto the MetaHuman skeleton, once per animation.

Both people scripts need the same thing: an ActorCore motion (recorded on the pack's Dummy_Male or
Dummy_Female) playing on a built MetaHuman body. The retarget is done once into
/Game/AMN/People/Animations and reused afterwards; seat_employees.py takes the seated loops from
here, street_people.py the walking and standing ones.
"""

import unreal

ANIM_OUT = "/Game/AMN/People/Animations"
MH_IK_RIG = "/MetaHumanCharacter/Animation/Retargeting/IK_MH_IKRig"
ACTORCORE = "/Game/ActorCore_Sample_Motions"


def log(msg):
    unreal.log(f"AMN_RETARGET {msg}")


def asset_of_class(folder, class_name, name_part=""):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    found = [a for a in registry.get_assets_by_path(folder, recursive=True)
             if str(a.asset_class_path.asset_name) == class_name and name_part.lower() in str(a.asset_name).lower()]
    return sorted(found, key=lambda a: str(a.package_name))


def retargeted(dummy, anim_rel, target_mesh):
    """The ActorCore animation `anim_rel` (under the pack, recorded on `dummy`) on the MetaHuman
    skeleton of `target_mesh`. Cached: the copy is named <source>_MH in ANIM_OUT."""
    # the batch retarget names its copy <source>_MH; match the name exactly ("Male_Sit_talk_Anim_MH"
    # is a substring of "Female_Sit_talk_Anim_MH")
    out_name = anim_rel.rsplit("/", 1)[1] + "_MH"
    existing = [a for a in asset_of_class(ANIM_OUT, "AnimSequence") if str(a.asset_name) == out_name]
    if existing:
        return unreal.load_asset(str(existing[0].package_name))
    source_anim = unreal.load_asset(f"{ACTORCORE}/{anim_rel}")
    source_mesh = unreal.load_asset(f"{ACTORCORE}/{dummy}/{dummy}")
    source_rig = unreal.load_asset(f"{ACTORCORE}/{dummy}/{dummy}_IKRig")
    target_rig = unreal.load_asset(MH_IK_RIG)
    if not all((source_anim, source_mesh, source_rig, target_rig, target_mesh)):
        raise RuntimeError(f"missing retarget input for {anim_rel}: anim={bool(source_anim)} mesh={bool(source_mesh)} "
                           f"source_rig={bool(source_rig)} target_rig={bool(target_rig)} target_mesh={bool(target_mesh)}")
    rtg_name = f"RTG_{dummy}_to_MH"
    rtg_path = f"{ANIM_OUT}/{rtg_name}"
    if unreal.EditorAssetLibrary.does_asset_exist(rtg_path):
        retargeter = unreal.load_asset(rtg_path)
    else:
        retargeter = unreal.AssetToolsHelpers.get_asset_tools().create_asset(rtg_name, ANIM_OUT, unreal.IKRetargeter, unreal.IKRetargetFactory())
    source, target = unreal.RetargetSourceOrTarget.SOURCE, unreal.RetargetSourceOrTarget.TARGET
    ctrl = unreal.IKRetargeterController.get_controller(retargeter)
    ctrl.set_ik_rig(source, source_rig)
    ctrl.set_ik_rig(target, target_rig)
    ctrl.set_preview_mesh(source, source_mesh)
    ctrl.set_preview_mesh(target, target_mesh)
    # 5.8 retargets through a stack of ops: create the default stack and point every op at the rigs
    # before mapping the chains, or the result is a still pose
    ctrl.add_default_ops()
    ctrl.assign_ik_rig_to_all_ops(source, source_rig)
    ctrl.assign_ik_rig_to_all_ops(target, target_rig)
    ctrl.auto_map_chains(unreal.AutoMapChainType.FUZZY, True)
    unreal.EditorAssetLibrary.save_loaded_asset(retargeter)
    # the batch operation takes registry entries, not loaded objects; arguments in the 5.8 order:
    # search, replace, prefix, suffix, target path, use source path, include referenced assets, overwrite
    anim_data = unreal.EditorAssetLibrary.find_asset_data(f"{ACTORCORE}/{anim_rel}")
    made = unreal.IKRetargetBatchOperation.duplicate_and_retarget(
        [anim_data], source_mesh, target_mesh, retargeter, "", "", "", "_MH", ANIM_OUT, False, False, True)
    log(f"{anim_rel} -> {[str(a.package_name) for a in made] if made else 'nothing'}")
    if made:
        return unreal.load_asset(str(made[0].package_name))
    found = [a for a in asset_of_class(ANIM_OUT, "AnimSequence") if str(a.asset_name) == out_name]
    return unreal.load_asset(str(found[0].package_name)) if found else None
