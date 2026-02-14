# Truthpack Sync Hook

## Trigger
Fires when any file in `.vibecheck/truthpack/` changes.

## Actions
1. **Detect changes**: Compare new truthpack hash with stored hash
2. **Identify deltas**: Find new/removed/changed routes, env vars, auth rules
3. **Update rules**: Refresh route lists and env var lists in all rules
4. **Update agents**: Give agents updated project context
5. **Update skills**: Refresh quick-reference data in skills
6. **Log change**: Record the sync event in the evolution ledger

## Change Types
- **New route added** → Update anti-hallucination guard route list
- **Route removed** → Flag as potential breaking change
- **New env var** → Update truthpack enforcer
- **Auth rule changed** → Alert security sentinel
- **Contract changed** → Update drift watcher

## Conflict Resolution
If a truthpack change conflicts with a manually-edited rule:
- Keep the manual edit
- Add a note about the conflict
- Flag for user review

---
<!-- vibecheck:context-engine:v1 -->