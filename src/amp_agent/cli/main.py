import time

from langchain_core.messages import HumanMessage

from ..agent.graph import graph


EXIT_COMMANDS = {
    "sair",
    "exit",
    "quit",
}


def main():
    print()
    print("AMP Agent")
    print("Router automático FAST / SMART")
    print("Digite 'sair' para encerrar.")
    print()

    while True:
        text = input("Você > ").strip()

        if not text:
            continue

        if text.lower() in EXIT_COMMANDS:
            print("Encerrando AMP Agent.")
            break

        started_at = time.perf_counter()

        try:
            result = graph.invoke(
                {
                    "messages": [
                        HumanMessage(
                            content=text
                        )
                    ],
                    # Valor inicial.
                    # O router irá sobrescrever.
                    "profile": "fast",
                }
            )

            elapsed = time.perf_counter() - started_at

            response = result["messages"][-1]
            profile = result["profile"]

            print()
            print(f"AMP > {response.content}")
            print()
            print(
                f"[execution] profile={profile} "
                f"time={elapsed:.2f}s"
            )
            print()

        except Exception as exc:
            elapsed = time.perf_counter() - started_at

            print()
            print(
                f"[error] falha após {elapsed:.2f}s: "
                f"{exc}"
            )
            print()


if __name__ == "__main__":
    main()