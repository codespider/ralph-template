# Ralph Loop - Task Runner

# Helper to verify a command exists
_check binary:
    @command -v {{binary}} >/dev/null 2>&1 || (echo "❌ Error: '{{binary}}' is not installed."; exit 1)

# Initialize a new Ralph loop in the current directory
init: (_check "claude") (_check "jq") (_check "python3")
    @echo "🚀 Initializing Ralph loop in {{invocation_directory()}}..."
    @mkdir -p "{{invocation_directory()}}/ralph/iterations"
    @cp ralph.sh "{{invocation_directory()}}/ralph/"
    @cp ralph.py "{{invocation_directory()}}/ralph/"
    @cp KERNEL.md "{{invocation_directory()}}/ralph/"
    @cp claude-cost-accounting.py "{{invocation_directory()}}/ralph/"
    @cp SPEC.md.template "{{invocation_directory()}}/ralph/SPEC.md"
    @cp PLAN.md.template "{{invocation_directory()}}/ralph/PLAN.md"
    @cp PROJECT.md.template "{{invocation_directory()}}/ralph/PROJECT.md"
    @touch "{{invocation_directory()}}/ralph/PROGRESS.md"
    @echo "✅ Ralph setup complete in ./ralph/"
    @echo "👉 Next: Fill in ralph/PROJECT.md and ralph/SPEC.md"

# Lint the project scripts
lint: (_check "shellcheck") (_check "ruff")
    @echo "🔍 Linting shell scripts..."
    shellcheck *.sh
    @echo "🔍 Linting Python files..."
    ruff check .

# Run a dry-run to verify the prompt concatenation
dry-run:
    @RALPH_DRY_RUN=1 ./ralph.sh --max 1

# Clean up local iteration logs
clean:
    rm -rf ralph/iterations/*
    rm -f ralph/RUN_STATUS ralph/COSTS.md ralph/COSTS.jsonl
