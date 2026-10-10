"""Exercise the startup boundary in Windows PowerShell without touching app data."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt", "Windows PowerShell regression")
class StartupBuildTests(unittest.TestCase):
    def run_start(self, exit_code):
        with tempfile.TemporaryDirectory(prefix="kw-start-test-") as folder:
            root = Path(folder)
            scripts = root / "scripts"
            scripts.mkdir()
            (root / "frontend/dist").mkdir(parents=True)
            (root / "frontend/dist/index.html").write_text("test build")
            (root / "logs").mkdir()
            shutil.copyfile(Path(__file__).resolve().parents[1] / "start.ps1", scripts / "start.ps1")
            (scripts / "common.ps1").write_text(r"""
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:KwProjectRoot = Split-Path $PSScriptRoot
$script:KwLogDir = Join-Path $script:KwProjectRoot 'logs'
function Initialize-KwRuntime { $env:KW_DATA_DIR = $script:KwProjectRoot }
function Install-KwDependencies {}
function Start-KwProcess {
    param($Name, $Executable, $Arguments, $Directory)
    if ($ErrorActionPreference -ne 'Stop') { throw 'Error policy was not restored' }
    Add-Content -LiteralPath (Join-Path $script:KwProjectRoot 'started.txt') -Value $Name
    return @{name=$Name}
}
function Save-KwProcesses {}
function Wait-KwHealth {}
""", encoding="utf-8")
            (root / "npm.cmd").write_text(
                "@echo off\necho [plugin builtin:vite-reporter] 1>&2\n"
                f"echo build finished\nexit /b {exit_code}\n", encoding="ascii")
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"]}
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "start.ps1")],
                env=env, cwd=root, capture_output=True, timeout=25)
            log = (root / "logs/build.log").read_bytes()
            started = (root / "started.txt").read_text() if (root / "started.txt").exists() else ""
            return result, log, started

    def test_successful_build_with_stderr_warning_starts_services(self):
        result, log, started = self.run_start(0)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn("api", started)
        self.assertIn("worker", started)
        self.assertIn("vite-reporter", log.decode("utf-16"))

    def test_failed_build_keeps_log_and_does_not_start_services(self):
        result, log, started = self.run_start(7)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(started, "")
        self.assertIn(b"Frontend build failed", result.stderr)
        self.assertIn("build finished", log.decode("utf-16"))


if __name__ == "__main__":
    unittest.main()
