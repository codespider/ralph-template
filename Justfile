# Ralph Loop - Task Runner

# Helper to verify a command exists
_check binary:
    @command -v {{binary}} >/dev/null 2>&1 || (echo "❌ Error: '{{binary}}' is not installed."; exit 1)

# Initialize a new Ralph loop in the current directory
init: (_check "claude") (_check "jq") (_check "python3")
    @echo "🚀 Initializing Ralph loop..."
    @mkdir -p ralph/iterations
    @cp ralph.sh ralph/
    @cp ralph.py ralph/
    @cp KERNEL.md ralph/
    @cp claude-cost-accounting.py ralph/
    @cp SPEC.md.template ralph/SPEC.md
    @cp PLAN.md.template ralph/PLAN.md
    @cp PROJECT.md.template ralph/PROJECT.md
    @touch ralph/PROGRESS.md
    @echo "✅ Ralph setup complete in ./ralph/"
    @echo "👉 Next: Fill in ralph/PROJECT.md and ralph/SPEC.md"

# Run a dry-run to verify the prompt concatenation
dry-run:
    @RALPH_DRY_RUN=1 ./ralph.sh --max 1

# Clean up local iteration logs
clean:
    rm -rf ralph/iterations/*
    rm -f ralph/RUN_STATUS ralph/COSTS.md ralph/COSTS.jsonl
