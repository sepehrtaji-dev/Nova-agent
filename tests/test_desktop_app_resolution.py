import unittest
from unittest.mock import patch

from tools.desktop import DesktopTool


class DesktopAppResolutionTests(unittest.TestCase):
    def setUp(self):
        self.desktop = DesktopTool()

    def test_unknown_application_is_error_and_never_launched(self):
        with (
            patch("tools.desktop.sys.platform", "win32"),
            patch("shutil.which", return_value=None),
            patch.object(self.desktop, "_get_windows_start_apps", return_value=[
                ("Mozilla Firefox", "Firefox.App"),
                ("Calculator", "Microsoft.WindowsCalculator"),
            ]),
            patch("tools.desktop.subprocess.Popen") as popen,
        ):
            result = self.desktop._action_open_app({"app": "calude"})

        self.assertIn("STATUS: ERROR", result)
        self.assertIn("No installed application matches 'calude'", result)
        popen.assert_not_called()

    def test_installed_application_is_resolved_without_name_hardcoding(self):
        with (
            patch("tools.desktop.sys.platform", "win32"),
            patch("shutil.which", return_value=None),
            patch.object(self.desktop, "_get_windows_start_apps", return_value=[
                ("Mozilla Firefox", "Firefox.App"),
            ]),
            patch("tools.desktop.subprocess.Popen") as popen,
            patch.object(self.desktop, "_screenshot", return_value=(
                "C:\\temp\\nova_after_open_app.png",
                None,
            )),
        ):
            result = self.desktop._action_open_app({"app": "firefox"})

        self.assertIn("STATUS: SUCCESS", result)
        self.assertIn("Opened: Mozilla Firefox", result)
        popen.assert_called_once_with(
            ["explorer.exe", "shell:AppsFolder\\Firefox.App"],
            stdout=unittest.mock.ANY,
            stderr=unittest.mock.ANY,
        )


if __name__ == "__main__":
    unittest.main()
