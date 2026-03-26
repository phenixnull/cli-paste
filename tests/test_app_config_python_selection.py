import unittest
from unittest import mock

import app_config


class PreferredPythonTests(unittest.TestCase):
    def test_prefers_explicit_python_env_for_console_launches(self):
        explicit = r".tools\python.exe"

        with mock.patch.dict(app_config.os.environ, {app_config.PYTHON_ENV_VAR: explicit}, clear=True), \
             mock.patch("app_config.os.path.exists", side_effect=lambda path: app_config.os.path.abspath(path) == app_config.os.path.abspath(explicit)), \
             mock.patch("app_config.shutil.which", return_value=r".path\python.exe"):
            self.assertEqual(
                app_config.os.path.abspath(explicit),
                app_config.get_preferred_python(),
            )

    def test_prefers_explicit_pythonw_env_for_windowless_launches(self):
        explicit = r".tools\pythonw.exe"

        with mock.patch.dict(app_config.os.environ, {app_config.PYTHONW_ENV_VAR: explicit}, clear=True), \
             mock.patch("app_config.os.path.exists", side_effect=lambda path: app_config.os.path.abspath(path) == app_config.os.path.abspath(explicit)), \
             mock.patch("app_config.shutil.which", return_value=r".path\pythonw.exe"):
            self.assertEqual(
                app_config.os.path.abspath(explicit),
                app_config.get_preferred_python(windowless=True),
            )

    def test_windowless_prefers_runtime_pythonw_sibling(self):
        runtime_python = r".runtime\python.exe"
        runtime_pythonw = r".runtime\pythonw.exe"

        with mock.patch.dict(app_config.os.environ, {}, clear=True), \
             mock.patch.object(app_config.sys, "_base_executable", runtime_python, create=True), \
             mock.patch("app_config.sys.executable", runtime_python), \
             mock.patch("app_config.os.path.exists", side_effect=lambda path: app_config.os.path.abspath(path) == app_config.os.path.abspath(runtime_pythonw)), \
             mock.patch("app_config.shutil.which", return_value=r".path\pythonw.exe"):
            self.assertEqual(
                app_config.os.path.abspath(runtime_pythonw),
                app_config.get_preferred_python(windowless=True),
            )

    def test_prefers_base_python_over_current_venv_runtime(self):
        base_python = r".base\python.exe"
        base_pythonw = r".base\pythonw.exe"
        venv_python = r".venv\Scripts\python.exe"

        with mock.patch.dict(app_config.os.environ, {}, clear=True), \
             mock.patch.object(app_config.sys, "_base_executable", base_python, create=True), \
             mock.patch("app_config.sys.executable", venv_python), \
             mock.patch("app_config.os.path.exists", side_effect=lambda path: app_config.os.path.abspath(path) == app_config.os.path.abspath(base_pythonw)), \
             mock.patch("app_config.shutil.which", return_value=r".path\pythonw.exe"):
            self.assertEqual(
                app_config.os.path.abspath(base_pythonw),
                app_config.get_preferred_python(windowless=True),
            )

    def test_windowless_falls_back_to_runtime_python_when_pythonw_is_missing(self):
        runtime_python = r".runtime\python.exe"

        with mock.patch.dict(app_config.os.environ, {}, clear=True), \
             mock.patch.object(app_config.sys, "_base_executable", runtime_python, create=True), \
             mock.patch("app_config.sys.executable", runtime_python), \
             mock.patch("app_config.os.path.exists", return_value=False), \
             mock.patch("app_config.shutil.which", return_value=None):
            self.assertEqual(
                app_config.os.path.abspath(runtime_python),
                app_config.get_preferred_python(windowless=True),
            )


if __name__ == "__main__":
    unittest.main()
