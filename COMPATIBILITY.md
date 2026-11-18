# PoB 2.68.1 启动兼容修复

本次更新修复 PoeCharm 3.6.0 在启动 Path of Building 2.68.1 时退出的问题。
关闭程序，将 **`PoeCharm3.exe` 和 `lua51.dll` 两个文件一起替换**到 PoeCharm 目录。
已更新的文件可以直接运行，无需安装 Python。

## 原因与改动

1. 旧 `lua51.dll` 不支持新版 PoB 的 `+=` 等语法，在 `Modules/Main:357` 的
   `count += 1` 处报出 `'=' expected near '+'`。运行库更新为 LuaJIT 2.1.1784580905，
   来源为 [PoB 2.68.1 的固定版本运行库](https://github.com/PathOfBuildingCommunity/PathOfBuilding/blob/a41fec6c20f822a658ae5df1273e8c69d5969bac/runtime/lua51.dll)。
2. 内嵌资源 `:/resources/lua/UTF8EditControl.lua` 使用旧类接口，加载时会报
   `attempt to concatenate local 'className' (a function value)`。
   已迁移为命名构造方法、`new("Class"):Class(...)` 和 `self:Parent(...)`，
   构造方法返回实例，原有 UTF-8 操作与翻译逻辑保留。

EXE 是对内嵌 Lua 资源的补丁，**未从 C++ 源码重新编译**。
改动限定在偏移 `0xCBE54C` 开始的 4714 字节压缩资源分配区，
文件大小、其他字节、资源索引及 PE 节偏移保持不变。
`fix_pob_compat.py` 提供可审阅、可重复执行的迁移与校验过程。

## 检查与复现

脚本适用于本仓库原版 PoeCharm 3.6.0，需 Python 3.8 或更高版本：

```sh
python fix_pob_compat.py --check
python fix_pob_compat.py --lua-dll /path/to/PoB-2.68.1/lua51.dll
```

未指定 `--lua-dll` 时，依次查找 EXE 目录下的
`PathOfBuildingCommunity-Portable/lua51.dll` 和相邻源码仓库的
`../PathOfBuilding/runtime/lua51.dll`。脚本校验文件哈希，拒绝未知版本，支持重复执行。
原文件保存在应用目录旁的 `../compat-backups/`；恢复时关闭程序，
将备份复制回应用目录，并恢复为 `PoeCharm3.exe` 和 `lua51.dll`。

| 文件 | 原版 SHA-256 | 更新后 SHA-256 |
| --- | --- | --- |
| `PoeCharm3.exe` | `e59521d6617afc76ef15fa908bee0f203f9b2c68bb772fb6f4284a4999db2cb9` | `69ff3b410e6b0c093e93afad13a2369966439bd1e656a4d89ab251324fdbffa0` |
| `lua51.dll` | `45f1067c805dc1b1e4bbc755e65cfd60561535686dd028ec709c6816c9abd43e` | `b11ad41b03d7aabe379fc38c1a490cfc53d7ab7d4d99c5bfadbbb27c09883e29` |

不同 zlib 编码器可能生成不同压缩字节；脚本同时核对解压后的 Lua 脚本哈希和资源区以外的字节。

## 验证

在仓库根目录运行：

```sh
python -B -m unittest discover -s tests -v
```

原始二进制从 Git 历史中的 `ac05b82ca47009780c1ebd6518108e876ccd44b5` 读取，
无需个人备份；浅克隆需包含该提交。检查覆盖交付文件、资源改动边界、重复修复、
异常文件拒绝、备份保护和 Lua DLL 更新。

安装 LuaJIT，并将 PoB 2.68.1 源码放在相邻 `../PathOfBuilding/src` 后，
还会使用真实 PoB 类定义复现旧错误，验证普通、数字、可清空、多行编辑框，
以及 ASCII 输入、撤销、重做、全选和替换。该项检查的外部库与图形 API 使用替身，
缺少依赖时明确跳过。

已在 Windows 使用 PoeCharm 3.6.0 和 PoB 2.68.1 实测启动，
确认中文主界面、3.30 天赋树和计算栏正常显示，初始化完成且无脚本错误。
尚未全面验证旧版 PoB、角色导入、交易、所有 BD 和中文编辑行为。
