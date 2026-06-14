from __future__ import annotations

import sys

from pine2ast.cli_commands import run_cli_command
from pine2ast.cli_parser import build_parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_cli_command(args)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(code)
