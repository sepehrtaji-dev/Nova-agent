import subprocess
import os



class TerminalTool:


    def __init__(self):

        self.history = []



    def run(self, command):


        self.history.append(
            command
        )


        blocked = [
            "format",
            "del /f",
            "rm -rf",
            "shutdown",
            "restart"
        ]


        for item in blocked:

            if item in command.lower():

                return "Command blocked for safety"



        try:

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )


            output = result.stdout


            if result.stderr:

                output += "\n" + result.stderr



            return output.strip()



        except Exception as e:

            return f"Terminal error: {e}"