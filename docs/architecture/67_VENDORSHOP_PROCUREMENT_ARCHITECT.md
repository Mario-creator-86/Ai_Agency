# VendorShop, Procurement & Asset Architect

## Concept

VendorShop is the studio's internal market-backed shop.

It does not stock arbitrary imaginary prices.
It sources real-world price evidence and sells the corresponding in-world item to the AI company for the same VR$ price.

It never performs external checkout.

## Roles

### Procurement Director / Buyer
Defines need and searches the market.

### VendorShop Manager
Converts approved market quotes into a virtual catalog/order.

### Asset Architect
Creates the top-down office-world visual asset after purchase.

### Finance
Approves affordability/budget.

### Legal/IP
Reviews public/branded representation when necessary.

## Purchase need

Examples:
- office chair;
- meeting table;
- couch;
- fountain;
- server rack decoration;
- coffee machine;
- room equipment.

PurchaseNeed contains:
- purpose;
- department;
- required features;
- dimensions/space limits;
- budget target;
- NEW / USED / EITHER;
- urgency;
- style constraints.

## Sourcing rules

For generic products:
- obtain multiple current quotes where possible;
- compare equivalent specs;
- record source URLs/identifiers;
- use transparent selection (selected listing, median, best-value score, etc.).

For exact requested product/model:
- use current exact listing if available;
- validate condition;
- validate price;
- include shipping/tax if known.

## Quote record

Store:
- product name/model;
- condition;
- seller/source;
- price;
- currency;
- FX snapshot;
- shipping;
- VAT/tax if known;
- location;
- source URL/reference;
- retrieved_at;
- expires_at;
- availability;
- confidence;
- comparable spec notes.

## Quote freshness

Quotes expire.
The purchase must revalidate a stale selected quote.

A used listing that disappears becomes unavailable and cannot be purchased at the old price unless policy explicitly uses a historical-market simulation rather than a live listing.

## Finance gate

Finance checks:
- treasury;
- runway;
- reserves;
- department budget;
- price reasonableness;
- used alternative;
- existing inventory;
- debt obligations.

## Virtual purchase

After approvals:
- ledger posts VR$ transaction;
- VendorShopOrder is committed;
- item becomes owned in virtual inventory;
- no real product order occurs.

## Asset Architect workflow

Input:
- exact selected product specification;
- legally usable references;
- dimensions;
- style bible;
- top-down perspective;
- collision footprint;
- placement target;
- color/material;
- brand restrictions.

Output:
- asset version;
- preview;
- sprite/visual files;
- footprint;
- metadata;
- fidelity notes;
- approval state.

If exact fidelity cannot be achieved, label deviation and request approval. Never silently create a different product.

## Delivery

Optional in-world delivery realism:
- immediate;
- quote-derived lead time;
- configured simulated lead time.

Delivery is a COMPANY_WORLD_EVENT, not a claim that a physical item arrived.

## Future resale

Architecture may later support:
- sell/dispose;
- real used-market revaluation;
- VendorShop buyback;
- upgrade/repair.
