# Reviewed actions

Selection of accounts, roles, people, paid/unknown operations, CRM changes and
message sending are distinct scopes. One explicit request may authorize the
associated draft or enrichment when scope and cost were presented together.
Approval of a draft never authorizes sending it.

Prepare the proposal, show exact items/fields/destinations/cost, allow exclusions,
and save explicit approval bound to proposal ID, revision, content digest and
connection identity. A changed target/content/owner invalidates that approval.
Every external effect is preceded by persisted intent and current blocking checks.

For native tools, the chat host runs prepare-action → native call → record-result.
The runtime cannot intercept arbitrary direct native calls. Supported hooks add
checks; the provider's permissions and native approvals remain in force.

CRM batches emit one item intent at a time with a parent-approved exact change;
partial outcomes remain visible. Unknown effects are reconciled before retry.
The pilot always requires explicit CRM/send approval and bounded consent for
paid or unknown-cost calls. Generic reads are not presumed free.
