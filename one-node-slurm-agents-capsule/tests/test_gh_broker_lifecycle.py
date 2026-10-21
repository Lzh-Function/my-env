"""Exercise generated broker startup/cleanup with real local child processes."""

import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "runtime/agentrun"


class BrokerLifecycleTests(unittest.TestCase):
    def test_helper_output_and_forced_shutdown_stay_in_log(self):
        with tempfile.TemporaryDirectory(prefix="broker lifecycle ") as directory:
            root = Path(directory)
            run = root / "run's logs"
            (run / "live").mkdir(parents=True)
            binary = root / "bin"
            binary.mkdir()
            fake = binary / "apptainer"
            fake.write_text(
                f"#!{sys.executable}\n"
                "import os, signal, socket, sys, time\n"
                "from pathlib import Path\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "mount = next(v for v in sys.argv if v.endswith(':/opt/gh-broker:rw'))\n"
                "directory = Path(mount.rsplit(':', 2)[0])\n"
                "server = socket.socket(socket.AF_UNIX)\n"
                "server.bind(str(directory / 'gh.sock'))\n"
                "print('HELPER_STDOUT', flush=True)\n"
                "print('HELPER_STDERR', file=sys.stderr, flush=True)\n"
                "while True: time.sleep(1)\n"
            )
            fake.chmod(0o755)
            generated = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1/agentrun"; GH_ENV_FILE="$2/gh.env"; gh_broker_launch_lines "$2" /image.sif',
                    "bash",
                    str(RUNTIME),
                    str(run),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            script = root / "apptainer_exec.sh"
            script.write_text(
                "#!/bin/bash\nset -euo pipefail\nsource "
                + shlex.quote(str(RUNTIME / "process-cleanup.sh"))
                + "\n"
                + generated.stdout
                + "exit 42\n"
            )
            result = subprocess.run(
                ["bash", str(script)],
                check=False,
                env=dict(os.environ, PATH=str(binary) + ":" + os.environ["PATH"]),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            log = (run / "live/gh_broker.log").read_text()
            self.assertIn("HELPER_STDOUT", log)
            self.assertIn("HELPER_STDERR", log)
            self.assertIn("強制停止", log)


if __name__ == "__main__":
    unittest.main()
