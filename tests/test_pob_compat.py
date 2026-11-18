import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "ac05b82ca47009780c1ebd6518108e876ccd44b5"
sys.path.insert(0, str(ROOT))
import fix_pob_compat as fix


def original_file(name, expected_sha256):
    """Read the verified original from repository history, without local backups."""
    data = subprocess.check_output(["git", "show", f"{BASELINE_COMMIT}:{name}"], cwd=ROOT)
    if fix.sha256(data) != expected_sha256:
        raise ValueError(f"Unexpected baseline file: {name}")
    return data


class CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = original_file("PoeCharm3.exe", fix.ORIGINAL_SHA256)
        cls.patched = fix.patch_image(cls.original)

    def test_packaged_files_are_updated(self):
        image = (ROOT / "PoeCharm3.exe").read_bytes()
        self.assertEqual(fix.inspect_image(image), "patched")
        self.assertEqual(fix.read_resource(image), fix.read_resource(self.patched))
        self.assertEqual(fix.inspect_lua((ROOT / "lua51.dll").read_bytes()), "updated")

    def test_only_embedded_resource_changes(self):
        self.assertEqual(len(self.original), len(self.patched))
        self.assertEqual(self.original[:fix.RESOURCE_OFFSET], self.patched[:fix.RESOURCE_OFFSET])
        self.assertEqual(self.original[fix.RESOURCE_END:], self.patched[fix.RESOURCE_END:])
        self.assertEqual(fix.inspect_image(self.patched), "patched")
        self.assertEqual(fix.sha256(fix.read_resource(self.patched)), fix.PATCHED_SOURCE_SHA256)

    def test_patch_is_idempotent(self):
        self.assertEqual(fix.patch_image(self.patched), self.patched)

    def test_unknown_exe_is_rejected(self):
        changed = bytearray(self.original)
        changed[0x400] ^= 1
        with self.assertRaisesRegex(ValueError, "不是已验证"):
            fix.patch_image(changed)

    def test_damaged_resource_is_rejected(self):
        changed = bytearray(self.original)
        changed[fix.RESOURCE_OFFSET:fix.RESOURCE_OFFSET + 4] = b"\xff" * 4
        with self.assertRaisesRegex(ValueError, "资源长度异常"):
            fix.patch_image(changed)

    def test_backup_and_repeated_file_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / "PoeCharm" / "PoeCharm3.exe"
            exe.parent.mkdir()
            exe.write_bytes(self.original)
            with contextlib.redirect_stdout(io.StringIO()):
                fix.patch_file(exe)
                fix.patch_file(exe)
            backup = exe.parent.parent / "compat-backups" / f"PoeCharm3.{fix.ORIGINAL_SHA256[:12]}.exe"
            self.assertEqual(backup.read_bytes(), self.original)
            self.assertEqual(exe.read_bytes(), self.patched)
            self.assertEqual(list(exe.parent.glob(".PoeCharm-compat-*")), [])

    def test_existing_different_backup_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / "PoeCharm" / "PoeCharm3.exe"
            exe.parent.mkdir()
            exe.write_bytes(self.original)
            backup = exe.parent.parent / "compat-backups" / f"PoeCharm3.{fix.ORIGINAL_SHA256[:12]}.exe"
            backup.parent.mkdir()
            backup.write_bytes(b"existing backup")
            with self.assertRaisesRegex(ValueError, "备份文件内容不符"):
                fix.patch_file(exe)
            self.assertEqual(exe.read_bytes(), self.original)
            self.assertEqual(backup.read_bytes(), b"existing backup")

    def test_real_pob_classes(self):
        interpreter = shutil.which("luajit")
        pob_src = ROOT.parent / "PathOfBuilding" / "src"
        if not interpreter or not pob_src.is_dir():
            self.skipTest("需要 LuaJIT 和相邻的 PathOfBuilding/src")
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.lua"
            migrated = Path(directory) / "migrated.lua"
            original.write_bytes(fix.read_resource(self.original))
            migrated.write_bytes(fix.read_resource(self.patched))
            result = subprocess.run(
                [interpreter, str(ROOT / "tests" / "editcontrol_compat.lua"), str(original), str(migrated)],
                cwd=pob_src, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("old class API error reproduced", result.stdout)
            self.assertIn("all EditControl behavior checks passed", result.stdout)

    def test_lua_upgrade_backs_up_and_is_idempotent(self):
        original = original_file("lua51.dll", fix.OLD_LUA_SHA256)
        updated = (ROOT / "lua51.dll").read_bytes()
        self.assertEqual(fix.inspect_lua(original), "original")
        self.assertEqual(fix.inspect_lua(updated), "updated")
        with tempfile.TemporaryDirectory() as directory:
            dll = Path(directory) / "PoeCharm" / "lua51.dll"
            dll.parent.mkdir()
            dll.write_bytes(original)
            with contextlib.redirect_stdout(io.StringIO()):
                fix.upgrade_lua(dll, updated)
                fix.upgrade_lua(dll, updated)
            backup = dll.parent.parent / "compat-backups" / f"lua51.{fix.OLD_LUA_SHA256[:12]}.dll"
            self.assertEqual(dll.read_bytes(), updated)
            self.assertEqual(backup.read_bytes(), original)

    def test_unknown_lua_source_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            dll = Path(directory) / "lua51.dll"
            dll.write_bytes(b"existing DLL")
            with self.assertRaisesRegex(ValueError, "来源 Lua DLL"):
                fix.upgrade_lua(dll, b"unknown DLL")
            self.assertEqual(dll.read_bytes(), b"existing DLL")


if __name__ == "__main__":
    unittest.main()
