from .db import run_migrations, setup_langgraph


def main() -> None:
    run_migrations()
    setup_langgraph()
    print("AMP migrations aplicadas.")


if __name__ == "__main__":
    main()
