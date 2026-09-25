import ctypes
import subprocess
import unittest
from unittest.mock import Mock, patch

import diagnostics as d


class HardwareTests(unittest.TestCase):
    def test_mac_reads_memory_and_chip_with_bounded_commands(self):
        with (
            patch.object(d.platform, "system", return_value="Darwin"),
            patch.object(d.platform, "machine", return_value="arm64"),
            patch.object(d.os, "cpu_count", return_value=12),
            patch.object(d.subprocess, "run", side_effect=[Mock(stdout=str(24 * 2**30)),
                                                         Mock(stdout="Apple M4 Pro\n")]) as run,
        ):
            hardware = d.scan_hardware()
            self.assertEqual(hardware.ram_gib, 24)
            self.assertEqual(hardware.cpu, "Apple M4 Pro")
            self.assertIsNone(hardware.available_gib)
            self.assertTrue(all(call.kwargs["timeout"] == 2 for call in run.call_args_list))

    def test_linux_parses_kib_and_available_memory(self):
        with (
            patch.object(d.platform, "system", return_value="Linux"),
            patch.object(d.Path, "read_text", return_value="MemTotal: 16777216 kB\nMemAvailable: 3145728 kB\n"),
        ):
            hardware = d.scan_hardware()
            self.assertEqual(hardware.ram_gib, 16)
            self.assertEqual(hardware.available_gib, 3)

    def test_windows_native_memory_structure(self):
        def fill(pointer):
            status = pointer._obj
            self.assertEqual(status.length, 64)
            status.total, status.available = 32 * 2**30, 12 * 2**30
            return 1

        library = Mock()
        library.kernel32.GlobalMemoryStatusEx.side_effect = fill
        with (
            patch.object(d.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", library, create=True),
        ):
            hardware = d.scan_hardware()
            self.assertEqual(hardware.ram_gib, 32)
            self.assertEqual(hardware.available_gib, 12)

    def test_failed_probe_does_not_guess_memory(self):
        with (
            patch.object(d.platform, "system", return_value="Darwin"),
            patch.object(d, "_sysctl", side_effect=subprocess.TimeoutExpired("sysctl", 2)),
        ):
            self.assertIsNone(d.scan_hardware().ram_gib)

    def test_malformed_linux_memory_is_unknown(self):
        with (
            patch.object(d.platform, "system", return_value="Linux"),
            patch.object(d.Path, "read_text", return_value="MemTotal: corrupt kB\n"),
        ):
            self.assertIsNone(d.scan_hardware().ram_gib)


class RecommendationTests(unittest.TestCase):
    def test_model_choices_for_supported_platforms(self):
        for system, arch, threads, ram, available, expected in (
            ("Darwin", "arm64", 12, 24, None, "medium"),
            ("Darwin", "arm64", 8, 8, None, "small"),
            ("Darwin", "arm64", 8, 16, None, "small"),
            ("Windows", "AMD64", 16, 32, 20, "small"),
            ("Windows", "AMD64", 4, 8, 6, "base"),
            ("Linux", "x86_64", 2, 4, 3, "tiny"),
            ("Linux", "x86_64", 16, 32, 1, "tiny"),
            ("Linux", "x86_64", 16, 32, 3, "base"),
        ):
            with self.subTest(system=system, ram=ram, available=available):
                lines = d.recommend_model(d.Hardware(system, arch, arch, threads, ram, available))
                self.assertIn(f"Empfehlung: {expected} ", lines[1])
                self.assertIn("Kein Geschwindigkeitstest", lines[-1])

    def test_large_is_not_automatically_preferred_over_latency(self):
        lines = d.recommend_model(d.Hardware("Darwin", "arm64", "Apple M4 Pro", 14, 48))
        self.assertIn("Empfehlung: medium", lines[1])
        self.assertIn("large-v3 testen", "\n".join(lines))

    def test_unsupported_and_incomplete_hardware_get_no_model_choice(self):
        for hardware in (
            d.Hardware("Darwin", "x86_64", "Intel", 16, 64),
            d.Hardware("Linux", "x86_64", "CPU", 8, None),
            d.Hardware("Windows", "AMD64", "CPU", None, 32),
        ):
            self.assertNotIn("Empfehlung: small", "\n".join(d.recommend_model(hardware)))
            self.assertFalse(any("(Einschätzung" in line for line in d.recommend_model(hardware)))

    def test_homeserver_is_not_recommended_using_client_hardware(self):
        with (
            patch.object(d.opentalk, "config", side_effect=lambda name, default="":
                         "https://home" if name == "SERVER_URL" else default),
            patch.object(d.opentalk, "recorder_dependency", return_value="/missing/recorder"),
            patch.object(d.shutil, "which", return_value=None),
            patch.object(d, "scan_hardware") as scan,
        ):
            lines = d.check_system()
            scan.assert_not_called()
            self.assertFalse(any(line.startswith("MODELL") for line in lines))
