import os


class FileSystemTool:
    def __init__(self):
        self.base_path = os.getcwd()

    def list_files(self, path="."):
        try:
            full_path = os.path.abspath(
                os.path.join(self.base_path, path)
            )

            if not os.path.exists(full_path):
                return f"Path does not exist: {path}"

            if not os.path.isdir(full_path):
                return f"Not a directory: {path}"

            files = os.listdir(full_path)

            if not files:
                return "Directory is empty."

            return "\n".join(files)

        except Exception as e:
            return f"Filesystem error: {e}"

    def read_file(self, path):
        try:
            full_path = os.path.abspath(
                os.path.join(self.base_path, path)
            )

            if not os.path.exists(full_path):
                return "File does not exist."

            if not os.path.isfile(full_path):
                return "Path is not a file."

            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            return content[:10000]

        except UnicodeDecodeError:
            return "File is not a UTF-8 text file."

        except Exception as e:
            return f"Filesystem error: {e}"