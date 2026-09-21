from agent.core import NovaCore


nova = NovaCore()

print("=" * 60)
print("NOVA CORE TEST")
print("=" * 60)

print()

while True:
    user = input("You: ")

    if user.lower() in {
        "exit",
        "quit",
    }:
        break

    if user.lower() == "/clear":
        nova.clear_context()
        print("Context cleared.")
        continue

    response = nova.chat(user)

    print(f"Nova: {response}")
    print()