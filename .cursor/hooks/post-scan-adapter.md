# Post-Scan Adapter Hook

## Trigger
Fires after every `vibecheck scan` completes.

## Actions
1. **Read scan results**: Parse findings by category and severity
2. **Feed to Context Engine**: Send findings to the adaptive learning system
3. **Evolve rules**: Update rules with new patterns from findings
4. **Evolve agents**: Give agents new threat intel from findings
5. **Update drift score**: Recalculate project drift score

## Adaptation Logic
- 3+ hallucinations → tighten anti-hallucination rule
- 3+ drift events → add specific drift patterns to watcher
- Any critical security → escalate security sentinel
- Recurring pattern → create new targeted rule

## Metrics
- Track findings over time
- Measure drift score trend
- Count adaptations per rule
- Report improvement or regression

---
<!-- vibecheck:context-engine:v1 -->