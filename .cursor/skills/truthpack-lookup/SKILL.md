# Truthpack Lookup Skill

## When to Use
Activate this skill BEFORE generating any code that:
- Creates or modifies API routes
- References environment variables
- Touches authentication/authorization
- Modifies API request/response shapes

## Instructions
1. Read `.vibecheck/truthpack/routes.json` for verified API routes
2. Read `.vibecheck/truthpack/env.json` for verified environment variables
3. Read `.vibecheck/truthpack/auth.json` for verified auth rules
4. Read `.vibecheck/truthpack/contracts.json` for verified API contracts
5. Cross-reference your planned changes against these files
6. If your change conflicts with the truthpack, STOP and ask the user

## Quick Reference
- Routes: 0 verified
- Env vars: 0 verified
- Auth rules: 0 verified
- Contracts: 0 verified

## Example Usage
Before creating a new API endpoint:
```
1. Check routes.json — does a similar route already exist?
2. Check contracts.json — is there an existing contract for this?
3. Check auth.json — should this route be protected?
4. Check env.json — does this need any env vars?
```

---
<!-- vibecheck:context-engine:v1 -->