#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "LinClip requires a Linux desktop session." >&2
  exit 1
fi

task_source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_install_dir="${XDG_DATA_HOME:-$HOME/.local/share}/linclip/venv"
task_bin_dir="$HOME/.local/bin"

command -v python3 >/dev/null || { echo "Install python3 and python3-venv first." >&2; exit 1; }
python3 -m venv "$task_install_dir"
"$task_install_dir/bin/python" -m pip install "$task_source_dir"
mkdir -p "$task_bin_dir"

# shlex.quote handles spaces and apostrophes in the interpreter path.
"$task_install_dir/bin/python" - "$task_bin_dir/linclip" <<'PY'
from pathlib import Path
import shlex
import sys
launcher = Path(sys.argv[1])
launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -m linclip "$@"\n')
launcher.chmod(0o755)
PY

"$task_bin_dir/linclip" --install-desktop
echo
echo "Installed: $task_bin_dir/linclip"
echo "Start: $task_bin_dir/linclip"
echo "Bind Super+V to: $task_bin_dir/linclip --toggle"
echo "Optional autostart: $task_bin_dir/linclip --autostart enable"
echo "Wayland: install wl-clipboard. X11 auto-paste: install xdotool."
