import textwrap
import unittest
from unittest import mock

import gui


class StartupTaskTests(unittest.TestCase):
    def test_startup_task_command_prefers_local_packaged_executable(self):
        with mock.patch.object(gui, "PACKAGED_EXE", r"dist\cli_paste.exe"), \
             mock.patch.object(gui, "WORKER_ARG", "--worker"), \
             mock.patch("gui.os.path.exists", side_effect=lambda path: path == r"dist\cli_paste.exe"), \
             mock.patch("gui.getattr", side_effect=getattr):
            self.assertEqual(
                [r"dist\cli_paste.exe", "--worker"],
                gui._get_startup_task_command(),
            )

    def test_worker_command_prefers_local_packaged_executable(self):
        with mock.patch.object(gui, "PACKAGED_EXE", r"dist\cli_paste.exe"), \
             mock.patch.object(gui, "WORKER_ARG", "--worker"), \
             mock.patch("gui.os.path.exists", side_effect=lambda path: path == r"dist\cli_paste.exe"), \
             mock.patch("gui.getattr", side_effect=getattr):
            self.assertEqual(
                [r"dist\cli_paste.exe", "--worker"],
                gui._get_worker_command(),
            )

    def test_task_definition_matches_packaged_executable_command(self):
        xml_text = textwrap.dedent(
            """
            <Task>
              <Actions Context="Author">
                <Exec>
                  <Command>dist\\cli_paste.exe</Command>
                  <Arguments>--worker</Arguments>
                </Exec>
              </Actions>
            </Task>
            """
        ).strip()

        expected = [r"dist\cli_paste.exe", "--worker"]

        self.assertTrue(gui._task_definition_matches_command(xml_text, expected))

    def test_task_definition_rejects_bootstrap_fallback_when_packaged_exe_expected(self):
        xml_text = textwrap.dedent(
            """
            <Task>
              <Actions Context="Author">
                <Exec>
                  <Command>pythonw.exe</Command>
                  <Arguments>"bootstrap.py" --worker</Arguments>
                </Exec>
              </Actions>
            </Task>
            """
        ).strip()

        expected = [r"dist\cli_paste.exe", "--worker"]

        self.assertFalse(gui._task_definition_matches_command(xml_text, expected))


if __name__ == "__main__":
    unittest.main()
