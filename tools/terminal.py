import subprocess


def run_command(command):

    allowed = [
        "python --version",
        "dir",
        "whoami"
    ]


    if command not in allowed:
        return "Command blocked"


    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True
    )


    return result.stdout