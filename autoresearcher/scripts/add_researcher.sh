#!/bin/bash
# add_researcher.sh <name>
#
# Scaffold a researcher plugin.
set -euo pipefail

NAME="${1:?usage: add_researcher.sh <name>}"
AUTORES=$(cd "$(dirname "$0")/.." && pwd)
SRC="$AUTORES/plugins/researchers/default"
DIR="$AUTORES/plugins/researchers/$NAME"

if [ -d "$DIR" ]; then
    echo "ERROR: $DIR already exists" >&2
    exit 1
fi
if [ ! -d "$SRC" ]; then
    echo "ERROR: default researcher agent not found at $SRC" >&2
    exit 1
fi

mkdir -p "$DIR/agents"
cp "$SRC/agents/"*.md "$DIR/agents/"

cat > "$DIR/README.md" <<MD
# $NAME researcher agent

Custom researcher agent scaffolded from the default 4. Edit
\`agents/*.md\` to adjust the research method.

If you keep the four dispatch points (Step 3a / 3b / 5 / 7.5) and the
files each writes, the default \`/autoresearch-redteam\` skill works
unchanged. If you change those, fork the skill at
\`.claude/skills/autoresearch-redteam-$NAME/\`.

To use:

\`\`\`bash
./scripts/launch_run.sh --researcher $NAME <run_code> <goal>
\`\`\`

See \`docs/PLUGINS.md\` + \`plugins/researchers/default/\` for the researcher-plugin layout.
MD

echo "Scaffolded $DIR with $(ls "$DIR/agents" | wc -l) agents copied from default"
echo "Next:"
echo "  1. Edit $DIR/agents/*.md to adjust the research method"
echo "  2. (Optional) Fork .claude/skills/autoresearch-redteam if dispatch steps change"
echo "  3. Test: ./scripts/launch_run.sh --researcher $NAME my_run 'goal'"
