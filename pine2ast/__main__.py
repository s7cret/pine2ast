from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    """Lazy console entrypoint.

    Importing ``pine2ast.__main__`` should be cheap for tests and embedding code;
    the heavier CLI module is imported only when the entrypoint is executed.
    """
    from pine2ast.cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
