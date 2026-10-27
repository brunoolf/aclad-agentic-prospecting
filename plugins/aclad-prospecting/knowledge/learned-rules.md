# Learned rules

This distributed file documents the format; it does not store seller preferences.
The private runtime Store is authoritative. Retrieve relevant active rules with
`rules` in the current trusted instance, following the
[session protocol](../references/session-protocol.md).

Each stored rule has an ID/revision, scope, instruction, status, creation/update
dates, short reason and evidence references. Status is `candidate`, `active` or
`revoked`. Only explicit reusable personal preferences become active through the
learning API. Account facts and product corrections stay in their original scope.
Unchanged output and silence create no rule.

Email and briefing generation selectively load the matching personal scope and
`personal:all`. Candidate and revoked rules are excluded. A company correction
must never become a universal writing instruction.

Repeated corrections preserve distinct evidence without duplicating the rule.
Review obsolete or conflicting rules with the seller and revoke by current
revision; retain the audit history. Reports are projections of private state and
cannot be edited as another source of truth. Personal knowledge is not exported
or shared by default, and examples remain private and seller-authorized.
