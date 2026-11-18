#!/usr/bin/env python3
"""Update PoeCharm 3.6.0's EditControl and Lua runtime for PoB 2.68.1."""

import argparse
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import zlib


ORIGINAL_SHA256 = "e59521d6617afc76ef15fa908bee0f203f9b2c68bb772fb6f4284a4999db2cb9"
ORIGINAL_SOURCE_SHA256 = "a765fa751d88f1745ab68ff5c48b552760f5960f42c109ca8b59f9c0b43b3919"
PATCHED_SOURCE_SHA256 = "1de0fc4a6c088a8f08b8fabd4221fe2175e4d9467d527b8bc4f161a9b7b0bc33"
# Qt stores a length, the uncompressed length, then a zlib stream. Preserve the
# original allocation so every other resource and PE section keeps its offset.
RESOURCE_OFFSET = 0xCBE54C
RESOURCE_CAPACITY = 4706
RESOURCE_END = RESOURCE_OFFSET + 8 + RESOURCE_CAPACITY
OUTSIDE_SHA256 = "93ab58c1178aa9a9948df5c93a9b98e0d5533fe67d73236053bd503fcd819923"
OLD_LUA_SHA256 = "45f1067c805dc1b1e4bbc755e65cfd60561535686dd028ec709c6816c9abd43e"
NEW_LUA_SHA256 = "b11ad41b03d7aabe379fc38c1a490cfc53d7ab7d4d99c5bfadbbb27c09883e29"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_resource(image):
    size, plain_size = struct.unpack_from(">II", image, RESOURCE_OFFSET)
    if not 4 < size <= RESOURCE_CAPACITY + 4:
        raise ValueError("内嵌资源长度异常，未修改文件。")
    stream = zlib.decompressobj()
    source = stream.decompress(image[RESOURCE_OFFSET + 8:RESOURCE_OFFSET + 4 + size])
    if not stream.eof or stream.unused_data or len(source) != plain_size:
        raise ValueError("内嵌资源校验失败，未修改文件。")
    return source


def inspect_image(image):
    # Checking all bytes outside the resource rejects other EXE versions and
    # unrelated modifications, while allowing different zlib encoder versions.
    if sha256(image[:RESOURCE_OFFSET] + image[RESOURCE_END:]) != OUTSIDE_SHA256:
        raise ValueError("不是已验证的 PoeCharm 3.6.0 EXE，或文件有其他修改；未修改文件。")
    source = read_resource(image)
    digest = sha256(source)
    if digest == PATCHED_SOURCE_SHA256:
        return "patched"
    if sha256(image) == ORIGINAL_SHA256 and digest == ORIGINAL_SOURCE_SHA256:
        return "original"
    raise ValueError("内嵌编辑框脚本不是已验证版本，未修改文件。")


def migrate_source(source):
    text = source.decode("utf-8")

    def replace(old, new, expected=1):
        nonlocal text
        if text.count(old) != expected:
            raise ValueError("旧脚本结构与预期不符，未修改文件。")
        text = text.replace(old, new)

    replace(
        'local EditClass = newClass("EditControl", "ControlHost", "Control", "UndoHandler", "TooltipHost", function(self, ',
        'local EditClass = newClass("EditControl", "ControlHost", "Control", "UndoHandler", "TooltipHost")\n\nfunction EditClass:EditControl(',
    )
    replace("\n\tself.protected = false\nend)", "\n\tself.protected = false\n\treturn self\nend")
    for name in ("ControlHost", "Control", "UndoHandler", "TooltipHost"):
        replace(f"self.{name}(", f"self:{name}(")
    for name, count in (("ButtonControl", 3), ("ScrollBarControl", 2)):
        replace(f'new("{name}", ', f'new("{name}"):{name}(', count)
    result = text.encode("utf-8")
    if sha256(result) != PATCHED_SOURCE_SHA256:
        raise ValueError("迁移后的脚本校验失败，未修改文件。")
    return result


def patch_image(image):
    if inspect_image(image) == "patched":
        return image
    source = migrate_source(read_resource(image))
    compressed = zlib.compress(source, level=9)
    if len(compressed) > RESOURCE_CAPACITY:
        raise ValueError("压缩后的脚本超出原资源空间，未修改文件。")
    block = struct.pack(">II", len(compressed) + 4, len(source)) + compressed
    block = block.ljust(RESOURCE_END - RESOURCE_OFFSET, b"\0")
    result = image[:RESOURCE_OFFSET] + block + image[RESOURCE_END:]
    if inspect_image(result) != "patched":
        raise ValueError("补丁校验失败，未修改文件。")
    return result


def patch_file(exe):
    image = exe.read_bytes()
    if inspect_image(image) == "patched":
        print(f"EXE 已迁移，无需重复操作：{exe}")
        return
    result = patch_image(image)
    # Store backups beside the application directory, outside its runtime files.
    backup = exe.parent.parent / "compat-backups" / f"PoeCharm3.{ORIGINAL_SHA256[:12]}.exe"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        if backup.read_bytes() != image:
            raise ValueError(f"备份文件内容不符，未覆盖：{backup}")
    else:
        with backup.open("xb") as file:
            file.write(image)
    replace_file(exe, image, result)
    print(f"EXE 已迁移：{exe}\n原版备份：{backup}")


def replace_file(path, before, result):
    # A running/locked Windows EXE or DLL fails without truncation.
    fd, temporary = tempfile.mkstemp(prefix=".PoeCharm-compat-", suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(result)
        os.chmod(temporary, path.stat().st_mode & 0o777)
        if path.read_bytes() != before:
            raise ValueError(f"操作期间文件已被其他程序修改，已停止替换：{path}")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def inspect_lua(image):
    digest = sha256(image)
    if digest == NEW_LUA_SHA256:
        return "updated"
    if digest == OLD_LUA_SHA256:
        return "original"
    raise ValueError("Lua DLL 不是已验证版本，未修改文件。")


def upgrade_lua(dll, source):
    if sha256(source) != NEW_LUA_SHA256:
        raise ValueError("来源 Lua DLL 不是已验证的 PoB 2.68.1 运行库，未修改文件。")
    before = dll.read_bytes()
    if inspect_lua(before) == "updated":
        print(f"Lua 运行库已更新：{dll}")
        return
    backup = dll.parent.parent / "compat-backups" / f"lua51.{OLD_LUA_SHA256[:12]}.dll"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        if backup.read_bytes() != before:
            raise ValueError(f"备份文件内容不符，未覆盖：{backup}")
    else:
        with backup.open("xb") as file:
            file.write(before)
    replace_file(dll, before, source)
    print(f"Lua 运行库已更新：{dll}\n原版备份：{backup}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", nargs="?", type=Path, default=Path(__file__).with_name("PoeCharm3.exe"))
    parser.add_argument("--check", action="store_true", help="只检查版本和补丁状态")
    parser.add_argument("--lua-dll", type=Path, help="PoB 2.68.1 配套 lua51.dll 的路径")
    args = parser.parse_args()
    try:
        exe = args.exe.resolve()
        exe_state = inspect_image(exe.read_bytes())
        dll = exe.with_name("lua51.dll")
        lua_state = inspect_lua(dll.read_bytes())
        if args.check:
            print("EXE：已迁移" if exe_state == "patched" else "EXE：原版，需要迁移")
            print("Lua：已更新" if lua_state == "updated" else "Lua：旧版，需要更新（不支持 += 等新语法）")
        else:
            source = dll.read_bytes()
            if lua_state == "original":
                candidates = [args.lua_dll] if args.lua_dll else [
                    exe.parent / "PathOfBuildingCommunity-Portable" / "lua51.dll",
                    exe.parent.parent / "PathOfBuilding" / "runtime" / "lua51.dll",
                ]
                source_path = next((p for p in candidates if p.is_file()), None)
                if source_path is None:
                    raise ValueError("未找到 PoB 的新 Lua DLL，请用 --lua-dll 指定路径。")
                source = source_path.read_bytes()
                if sha256(source) != NEW_LUA_SHA256:
                    raise ValueError("来源 Lua DLL 不是已验证的 PoB 2.68.1 运行库，未修改文件。")
            patch_file(exe)
            upgrade_lua(dll, source)
    except (OSError, ValueError, zlib.error, struct.error) as error:
        parser.exit(1, f"修复失败：{error}\n")


if __name__ == "__main__":
    main()
