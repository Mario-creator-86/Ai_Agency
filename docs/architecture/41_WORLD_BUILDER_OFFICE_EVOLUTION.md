# World Builder and Office Evolution

## Goal

Allow the Director to evolve the 2D office without requiring a developer for every new chair, fountain or room.

## Supported world primitives

- Room
- Wall/door
- Desk
- Seat
- DecorativeObject
- EquipmentObject
- Zone
- Path
- SpawnPoint
- InteractionPoint

## World asset

Fields:
- asset_id/version;
- sprite/atlas;
- dimensions;
- footprint;
- anchors;
- collision;
- allowed rotation;
- style tags;
- rights/provenance;
- VR$ acquisition cost / VendorShop / inventory metadata when applicable.

## Change flow

1. Director proposes change.
2. Governance/budget check.
3. Select existing asset OR request new asset.
4. Validate style/format.
5. Calculate placement.
6. Validate paths/collisions.
7. Preview.
8. Commit backend layout version.
9. Emit world event.
10. UI renders.

## Generated assets

If AI creates a new object:
- generation provider;
- prompt/reference;
- output hash;
- transparent background/format if required;
- style conformity;
- rights/provenance;
- technical validation.

## Room creation

Room templates may define:
- dimensions;
- capacity;
- department purpose;
- required doors;
- furniture constraints.

Director cannot invent an unsupported room behavior; it can combine supported primitives.

## Narrative integration

A committed world change becomes a HistoricalEvent and can appear in the next serial.

## Rollback

World layout versions allow rollback if a change is visually/operationally bad.


## V4 department/world integration

Department creation can trigger:
- sign;
- desks;
- zone;
- dedicated room proposal.

HR birthday/event can trigger temporary decorations with start/end lifecycle.

CompanyEvent may switch world scene:
- OFFICE
- OFFSITE_EVENT
- CELEBRATION
- MAINTENANCE
depending on implemented assets.

Persistent organization/world changes require backend commit.

Temporary decorations must have expiration/cleanup rules.


# V5 Market-Priced World Assets

Persistent office objects may originate from VendorShop procurement.

World Builder must receive a committed `InventoryAsset` and approved `AssetArchitectJob` before marking a market-priced item as owned/delivered.

Lifecycle:
PurchaseNeed
→ quote
→ approval
→ VR$ purchase
→ inventory asset
→ visual asset generation
→ validation
→ delivery event
→ placement
→ world state commit.

Preview assets may exist before purchase but must be labeled PREVIEW and cannot be treated as owned.

Future optional lifecycle:
- depreciation;
- resale at market-backed used price;
- disposal;
- repair/upgrade;
- relocation.
