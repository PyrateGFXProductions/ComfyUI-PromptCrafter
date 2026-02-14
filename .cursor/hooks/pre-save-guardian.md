# Pre-Save Guardian Hook

## Trigger
Fires on every file save in the workspace.

## Checks
1. **Import Validation**: Verify all imports resolve to real modules
2. **Env Var Check**: Flag any hardcoded secrets or unknown env vars
3. **Pattern Compliance**: Ensure code follows established patterns
4. **Type Safety**: Flag any `as any` or type assertion abuse

## Blocking Conditions
- Hardcoded API keys or secrets → BLOCK
- Import of non-existent module → WARN
- New env var not in .env.example → WARN
- `console.log` in production code → INFO

## Auto-Actions
- Format file on save
- Sort imports
- Remove unused imports
- Update truthpack if route file changed

---
<!-- vibecheck:context-engine:v1 -->