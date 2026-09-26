from agent.core import NovaCore


def main():
    nova = NovaCore()

    print("=" * 50)
    print("Nova AI Agent")
    print("Brain: Llama 3.2 3B (Ollama)")
    print("Type 'exit' to quit")
    print("=" * 50)

    while True:
        user = input("\nYou: ")

        if user.lower() in ["exit", "quit"]:
            break

        answer = nova.ask(user)

        print("\nNova:", answer)


if __name__ == "__main__":
    main()