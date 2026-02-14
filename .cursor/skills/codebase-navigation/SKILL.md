# Codebase Navigation Skill

## When to Use
Activate this skill when:
- You need to find where something is implemented
- You need to understand the project structure
- You need to find related files for a change
- You need to understand the dependency graph

## Instructions
1. **Start with truthpack**: The truthpack maps routes → files, giving you entry points
2. **Follow imports**: Trace the import chain to understand dependencies
3. **Check neighbors**: Files in the same directory usually follow the same patterns
4. **Read tests**: Test files reveal intended behavior and edge cases
5. **Check configs**: tsconfig, package.json, and .env reveal project setup

## Project Map
### API Entry Points
- Run a scan to map routes

### Key Environment
- Run a scan to map env vars

## Navigation Tips
- Use the truthpack as your map — it's verified ground truth
- When lost, start from the route handler and trace inward
- Check `.vibecheck/truthpack/meta.json` for project summary

---
<!-- vibecheck:context-engine:v1 -->