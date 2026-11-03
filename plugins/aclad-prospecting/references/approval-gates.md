# Reviewed actions

Selection of accounts, roles, people, paid/unknown operations, CRM changes and
message sending are distinct scopes. One explicit request may authorize the
associated draft or enrichment when scope and cost were presented together.
Approval of a draft never authorizes sending it.

Prepare the proposal, show exact items/fields/destinations/cost, allow exclusions,
and save explicit approval bound to proposal ID, revision, content digest and
connection identity. A changed target/content/owner invalidates that approval.
Every external effect is preceded by persisted intent and current blocking checks.

For native tools, the host binds actual arguments with proposal-bind-native
before approval; binding changes revision/digest and invalidates older approval.
Then approve → prepare-action → native call with payload.native_request.input →
record-result. Domain payloads are not native tool arguments. A first untested
operation on an authenticated account uses explicit operation_validation approval,
even for a free query, and bounded search limits; denied operations remain blocked.
The runtime cannot intercept arbitrary direct native calls. Supported hooks add
checks; the provider's permissions and native approvals remain in force.

CRM batches emit one item intent at a time with a parent-approved exact change;
partial outcomes remain visible. Unknown effects are reconciled before retry.
The pilot always requires explicit CRM/send approval and bounded consent for
paid or unknown-cost calls. Generic reads are not presumed free.

Guided setup completion and connector readiness are distinct from action approval.
A connected account never authorizes credits, CRM writes or message sends. A
read-only CRM can complete the connection block, but cannot perform write actions.
Accounts/contacts still require confirmed CRM state for draft/send; do not fabricate
confirmation or call native tools directly when an operational prerequisite fails.
For an account already in the CRM, reconcile verified existing records instead of
requiring an unnecessary create. Preserve unknown-effects and provider proof rules.
