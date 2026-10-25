#!/bin/bash

# 1. Isolate changes to a new branch
git checkout -b style/equa-night-refactor

# 2. Cap iterations to control API costs (e.g., 10 loops)
for i in {1..10}; do
    echo "=== Starting Agent Loop $i ==="
    
    # 3. Call Claude Code. 
    # Pipe 'yes' to automatically approve tool execution prompts.
    yes | claude -p "Review the Equa Next.js and FastAPI codebase. Identify one specific area for code quality refinement or performance optimization, implement the fix, run pre-commit, and resolve any errors."
    
    # 4. Stage and commit the results
    git add .
    git commit -m "refactor(agent): automated overnight refinement $i"
    
    # Optional: Push to remote so Vercel builds it (if on main) or for backup
    git push origin style/equa-night-refactor
    
    echo "=== Loop $i complete. Cooling down for 60s. ==="
    sleep 60
done
