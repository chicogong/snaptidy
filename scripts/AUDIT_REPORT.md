# SnapTidy 代码质量深度审计报告

审计范围: `/Users/haorangong/Github/snaptidy/scripts/` 下全部 10 个 Python 脚本
审计日期: 2026-06-16

---

## 严重性定义

| 级别 | 含义 |
|------|------|
| **P0** | 安全漏洞或数据丢失风险，必须立即修复 |
| **P1** | 逻辑错误或资源泄漏，可能导致运行时故障 |
| **P2** | 代码质量/性能/兼容性问题，建议修复 |

---

## 1. Security (安全)

### S-01 AppleScript 命令注入 — `apply_move_plan.py:39`

**严重性: P0**

```python
result = subprocess.run(
    ["osascript", "-e", f'tell application "Finder" to delete POSIX file "{path}"'],
    ...
)
```

`path` 来自 CSV 输入，若包含 `"` 可逃逸 AppleScript 字符串，导致任意 Finder 操作。攻击者可构造 `"; do shell script "rm -rf /"; "` 形路径。

**建议修复**: 使用 `subprocess.run(["osascript", "-e", script], ...)` 并对 `path` 中的 `"` 和 `\` 进行转义，或使用 POSIX file 的 AppleScript 引用方式避免字符串拼接。

---

### S-02 AppleScript 命令注入 — `import_to_photos.py:483-495`

**严重性: P0**

```python
script = f'''
tell application "Photos"
    set targetAlbum to album "{album_name}"
    import POSIX file "{file_path}" into targetAlbum skip check duplicates {skip_str}
end tell
'''
```

`album_name` 和 `file_path` 均来自用户输入或命令行参数，直接插入 AppleScript 字符串，可被注入。

**建议修复**: 对 `album_name` 和 `file_path` 中的双引号进行转义（`"` → `\\"`），或改用 ScriptingBridge API（已有 `import_via_scriptingbridge` 实现）。

---

### S-03 AppleScript 命令注入 — `import_to_photos.py:579`

**严重性: P0**

```python
script = f'''
tell application "Photos"
    make new album named "{album_name}"
end tell
'''
```

同 S-02，`album_name` 未转义。

**建议修复**: 同 S-02。

---

### S-04 AppleScript 命令注入 — `import_to_photos.py:842-866`

**严重性: P0**

```python
script = f'''
tell application "Photos"
    ...
    set targetAlbum to album "{album_name}"
    ...
    set keywords of aPhoto to (keywords of aPhoto) & "{keyword}"
    ...
end tell
'''
```

`album_name` 和 `keyword` 均未转义，可注入任意 AppleScript。

**建议修复**: 对所有用户可控字符串进行 AppleScript 转义，或仅使用 ScriptingBridge。

---

### S-05 f-string SQL 列名注入 — `scan_photos.py:486`

**严重性: P2**

```python
cols = ", ".join(entry.keys())
placeholders = ", ".join("?" for _ in entry)
conn.execute(f"INSERT OR REPLACE INTO photos ({cols}) VALUES ({placeholders})",
             list(entry.values()))
```

当前 `entry.keys()` 由代码硬编码字典生成，无用户输入风险。但此模式若被复制到其他场景且字典键来自外部，则存在 SQL 注入风险。`scan_photos_library.py:339` 和 `quick_scan.py:143` 中的 `f"CREATE INDEX IF NOT EXISTS {idx} ON photos({col})"` 同理。

**建议修复**: 使用白名单验证列名，或将列名固定为常量列表而非 `entry.keys()`。

---

### S-06 f-string SQL 动态表名 — `scan_photos_library.py:381,397-404`

**严重性: P1**

```python
j_cols = [row[1] for row in photos_db.execute(f"PRAGMA table_info({junction_table})").fetchall()]
...
cursor = photos_db.execute(f"""
    SELECT ja.{asset_col} AS asset_pk, ...
    FROM {junction_table} ja
    JOIN ZGENERICALBUM ga ON ja.{album_col} = ga.Z_PK
    ...
""")
```

`junction_table` 从 `sqlite_master` 查询动态获取，`asset_col` / `album_col` 来自 `PRAGMA table_info` 结果。虽然来源是受信任的 Photos.sqlite 结构，但若数据库被篡改或替换，恶意表名/列名可导致 SQL 注入。

**建议修复**: 用正则验证 `junction_table` 匹配 `^Z_\d+ASSETS$`，验证列名匹配 `^[A-Z_]\w*$`。

---

### S-07 HTML 生成中未转义的路径 — `generate_preview.py:216`

**严重性: P1**

```python
thumb_html = f'<img class="thumbnail" src="data:image/jpeg;base64,{thumb_b64}" alt="{fname_escaped}">'
```

`fname_escaped` 使用 `html.escape()` 转义，是安全的。但同文件第 167-172 行中 `total_groups`、`label` 等值虽源自数据，未经 `html.escape()` 处理直接插入 f-string HTML。若 `match_type` 包含恶意内容（如 `<script>` 标签），可导致 XSS。

**建议修复**: 对所有动态 HTML 插值使用 `html.escape()`，或使用模板引擎。

---

### S-08 `__import__()` 反模式 — `apply_move_plan.py:263,279`

**严重性: P2**

```python
"expires_at": (datetime.now() + __import__("datetime").timedelta(days=30)).isoformat(),
...
__import__("json").dump(record, f, indent=2, ensure_ascii=False)
```

`__import__()` 可被滥用（若模块名来自外部输入），此处虽为硬编码，但违反安全编码最佳实践。

**建议修复**: 在文件顶部正常 `import json; from datetime import timedelta`。

---

## 2. Error Handling (错误处理)

### E-01 裸 `except Exception` 吞异常 — 多文件

**严重性: P1**

| 文件 | 行号 | 函数 |
|------|------|------|
| `generate_preview.py` | 50 | `get_thumbnail_base64()` |
| `scan_photos.py` | 173,215,232,246,255,264 | 多个 EXIF/图像函数 |
| `scan_photos_library.py` | 101,113,124,135,157,176,214,233,249 | 同上 |
| `apply_move_plan.py` | 46,241 | `move_to_trash()`, `compute_file_checksum()` |

所有 `except Exception: return ""` / `pass` 模式静默吞掉错误，使得调试困难。特别在 `get_thumbnail_base64()` 中返回空字符串时，调用方无法区分"图片损坏"和"图片不存在"。

**建议修复**: 至少用 `logging.warning()` 记录异常信息；对关键路径使用更具体的异常类型。

---

### E-02 SQLite 连接未使用上下文管理器 — `generate_preview.py:85-91`

**严重性: P1**

```python
conn = sqlite3.connect(index_db)
...
conn.close()
```

若 `conn.execute()` 与 `conn.close()` 之间抛出异常，连接将泄漏。

**建议修复**: 使用 `with sqlite3.connect(...) as conn:` 或 `try/finally`。

---

### E-03 SQLite 连接未使用上下文管理器 — `organize_photos.py:426-451`

**严重性: P1**

`show_preview()` 函数中 `conn = sqlite3.connect(index_db)` 在循环中每行查询，若异常则连接泄漏。同文件 `generate_by_date_plan()` (行 282)、`generate_by_category_plan()` (行 371) 也有相同问题。

**建议修复**: 使用 `with` 语句或 `try/finally` 确保关闭。

---

### E-04 临时文件异常路径未清理 — `quick_scan.py:236-245`

**严重性: P1**

```python
with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
    tmp_db_path = tmp.name
shutil.copy2(db_path, tmp_db_path)
photos_db = sqlite3.connect(tmp_db_path)
```

若 `shutil.copy2()` 或后续操作抛出异常，`tmp_db_path` 不会被清理（对比 `scan_photos_library.py` 使用了 `try/finally` 清理）。

**建议修复**: 用 `try/finally` 包裹，确保 `os.unlink(tmp_db_path)` 被执行。

---

### E-05 自身模块导入 — `apply_move_plan.py:405`

**严重性: P1**

```python
from apply_move_plan import save_undo_record
```

在 `main()` 函数内部从自身模块导入 `save_undo_record`，这在脚本直接运行时是多余的（函数已在同一模块中），且在打包或测试时可能导致 `ImportError` 或双重初始化。

**建议修复**: 直接调用 `save_undo_record()`，无需从模块导入。

---

### E-06 `download_icloud_file()` 只读 1 字节 — `organize_photos.py:587-588`

**严重性: P2**

```python
with open(path, "rb") as f:
    f.read(1)
return True
```

仅读取 1 字节未必能触发 iCloud 下载。对于较大的 iCloud 占位文件，macOS 可能需要更多访问才能启动下载。且 `open()` 本身可能失败但不报错。

**建议修复**: 使用 `brctl download`（已在 `try` 块中实现），移除不可靠的 `f.read(1)` fallback，或至少读一个更大的块。

---

### E-07 `find_duplicates_db()` 未过滤空 sha256 — `find_exact_duplicates.py:28-33`

**严重性: P1**

```python
cursor = conn.execute("""
    SELECT sha256, file_path, size_bytes, category, format_family
    FROM photos
    WHERE sha256 IN (
        SELECT sha256 FROM photos
        GROUP BY sha256
        HAVING COUNT(*) > 1
    )
    ...
""")
```

未过滤 `sha256 = ''` 或 `sha256 IS NULL`。若扫描过程中某些文件 hash 失败（返回空字符串），空 hash 的所有文件将被归为同一组。

**建议修复**: 在子查询中添加 `WHERE sha256 != '' AND sha256 IS NOT NULL`。`quick_scan.py:406-408` 已正确处理此问题。

---

### E-08 信号处理器中使用 `sys.exit()` — `import_to_photos.py:738`

**严重性: P2**

```python
def _save_checkpoint_on_signal(signum, frame):
    ...
    sys.exit(130)
```

信号处理器中调用 `sys.exit()` 会触发 `SystemExit` 异常，可能中断正在进行的文件操作。

**建议修复**: 使用 `signal.signal()` 设置标志位，在主循环中检查并优雅退出；或确保 `sys.exit()` 前所有关键状态已持久化。

---

## 3. Logic Bugs (逻辑错误)

### L-01 循环中删除字典键 — `organize_photos.py:190-192`

**严重性: P1**

```python
for extra_key in list(r.keys()):
    if extra_key not in ("group_id", "file_path", "phash", "match_type"):
        del r[extra_key]
```

虽使用 `list(r.keys())` 避免了 `RuntimeError`，但直接修改 `find_duplicates_db()` 返回的字典对象，可能影响调用方的后续使用。这是一个副作用操作。

**建议修复**: 创建新字典而非修改原字典：`r = {k: v for k, v in r.items() if k in keep_keys}`。

---

### L-02 `entries` 列表构建但几乎未使用 — `scan_photos_library.py:469,640`

**严重性: P2**

```python
entries = []  # Kept only for HEIC count in stats; entries are streamed to DB
...
entries.append(entry_dict)
```

`entries` 列表将所有条目保存在内存中，但仅用于统计 HEIC 数量（可在循环中直接计数）。对于大型照片库（数万条目），这是不必要的内存浪费。

**建议修复**: 移除 `entries.append(entry_dict)` 和 `entries = []`，HEIC 计数已在循环中通过 `heic_count += 1` 完成。

---

### L-03 `write_human()` 中 O(n) 查找重复计算 — `find_exact_duplicates.py:121-126`

**严重性: P2**

```python
meta = group_meta.get(entries[0]["sha256"], [])
size = 0
for m in meta:
    if m["path"] == e["file_path"]:
        size = m["size"]
        break
```

对于组内每个文件，线性搜索 `group_meta` 列表。组内有 n 个文件时，总复杂度为 O(n²)。

**建议修复**: 将 `group_meta` 列表转为 `dict: path → size`，实现 O(1) 查找。

---

### L-04 `os.makedirs` 静默失败 — `find_exact_duplicates.py:165`

**严重性: P2**

```python
os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
```

三元表达式作为语句使用，不符合惯用写法。若 `os.path.dirname()` 为空字符串，`os.makedirs("", ...)` 不会报错但也不会创建目录，可能导致后续文件写入失败。

**建议修复**: 使用标准 `if` 语句，并在 `os.makedirs` 失败时让异常自然传播。

---

### L-05 Union-Find 路径压缩不完整 — `find_similar_photos.py:617-621`

**严重性: P2**

```python
def find(x):
    while parent.get(x, x) != x:
        parent[x] = parent.get(parent[x], parent[x])  # path compression
        x = parent[x]
    return x
```

路径压缩仅做了一步（将节点指向祖父），不是完全路径压缩。对于大型集合，这可能导致 `find()` 仍为 O(log n) 而非 O(α(n))。

**建议修复**: 使用递归或完整迭代路径压缩：`while parent.get(x, x) != x: parent[x] = find(parent[x]); x = parent[x]`。但需注意 Python 递归深度限制。

---

### L-06 `get_icloud_storage_info()` 硬编码路径 — `import_to_photos.py:372`

**严重性: P2**

```python
library_path = os.path.expanduser("~/Pictures/Photos Library.photoslibrary")
```

若用户移动了照片库位置（常见于外置存储），此函数将返回错误结果。虽然后续有遍历 `~/Pictures` 的 fallback，但 `os.statvfs()` 可能对不存在的路径失败。

**建议修复**: 接受 `library_path` 参数，由调用方传入实际路径。

---

## 4. Performance (性能)

### P-01 逐行 SQLite COMMIT — `scan_photos.py:557`

**严重性: P1**

```python
_insert_entry(conn, entry)
conn.commit()  # Commit every entry — zero data loss on crash
```

每条记录一次 COMMIT，对 WAL 模式下的 SQLite 仍造成严重性能退化。10 万张照片的扫描可能从几秒变为几分钟。

**建议修复**: 使用批量 COMMIT（每 100 或 1000 条提交一次），配合 `INSERT OR REPLACE` 的幂等性保证重启后安全。或使用事务块：
```python
for idx, entry in enumerate(entries):
    _insert_entry(conn, entry)
    if idx % 1000 == 0:
        conn.commit()
conn.commit()
```

---

### P-02 逐行 SQLite COMMIT — `quick_scan.py:202,378`

**严重性: P1**

同 P-01，`quick_scan.py` 的 `scan_directory()` 和 `scan_photos_library()` 中也存在逐行提交。

**建议修复**: 同 P-01。

---

### P-03 逐行 SQLite COMMIT — `scan_photos_library.py:648`

**严重性: P1**

```python
_insert_entry(out_conn, entry_dict)
out_conn.commit()
```

同 P-01。

**建议修复**: 同 P-01。

---

### P-04 全表 SELECT * 加载 — `generate_preview.py:88`

**严重性: P2**

```python
cursor = conn.execute("SELECT * FROM photos")
for row in cursor:
    metadata[row["file_path"]] = dict(row)
```

加载整个 `photos` 表到内存（包含所有列），但实际只使用了 `filename`, `extension`, `width`, `height`, `size_bytes`, `category`, `folder_tag`, `has_exif`, `camera_model` 这几列。对于大型数据库（10 万+行），这会消耗大量内存。

**建议修复**: 使用 `SELECT file_path, filename, extension, width, height, size_bytes, category, folder_tag, has_exif, camera_model FROM photos`。

---

### P-05 全表 SELECT * 加载 — `generate_move_plan.py:46`

**严重性: P2**

```python
cursor = conn.execute("SELECT * FROM photos")
```

同 P-04，加载所有列到内存。

**建议修复**: 仅 SELECT 需要的列。

---

### P-06 O(n²) 模糊 pHash 匹配 — `find_similar_photos.py:81-98`

**严重性: P2**

```python
for i, (ph1, path1) in enumerate(all_entries):
    ...
    for j in range(i + 1, len(all_entries)):
        ...
        if hash1 - hash2 <= threshold:
```

对 n 条记录进行 O(n²) 比较。注释中已标注 "slower, pairwise comparison"。

**建议修复**: 使用 BK-tree 或局部敏感哈希（LSH）将复杂度降至 O(n log n)；或对 pHash 排序后仅比较相邻项。

---

### P-07 O(n²) Apple Quality Vector 余弦相似度 — `find_similar_photos.py:629-648`

**严重性: P2**

```python
for i in range(len(entries_with_vector)):
    ...
    for j in range(i + 1, len(entries_with_vector)):
```

对所有具有质量向量的条目进行 O(n²) 余弦相似度比较。

**建议修复**: 使用 FAISS、Annoy 或 scikit-learn 的近似最近邻搜索。

---

### P-08 `format_size`/`format_bytes` 函数重复定义 — 多文件

**严重性: P2**

| 文件 | 行号 | 函数名 |
|------|------|--------|
| `generate_preview.py` | 54-62 | `format_size` |
| `organize_photos.py` | 455-463 | `format_bytes` |
| `generate_move_plan.py` | 302-309 (inline) | inline |
| `find_exact_duplicates.py` | 87-95 | `format_size` |
| `find_similar_photos.py` | 744-749 (inline) | inline |

同一逻辑重复实现 5 次，且名称不统一（`format_size` vs `format_bytes`），单位后缀也不一致（"B" vs "bytes"）。

**建议修复**: 提取到共享模块 `utils.py` 中。

---

## 5. Compatibility (兼容性)

### C-01 macOS 专有功能无跨平台降级 — 多文件

**严重性: P2**

| 文件 | 功能 | 依赖 |
|------|------|------|
| `apply_move_plan.py` | `move_to_trash()` 使用 osascript | macOS only |
| `apply_move_plan.py` | `move_photos_to_trash()` 使用 PyObjC | macOS only |
| `import_to_photos.py` | 全部导入功能 | macOS only |
| `organize_photos.py` | `check_icloud_status()` 使用 xattr | macOS only |
| `organize_photos.py` | `download_icloud_file()` 使用 brctl | macOS only |
| `organize_photos.py` | `detect_android_mount()` 使用 /Volumes/ | macOS only |
| `organize_photos.py` | `detect_external_drives()` 使用 /Volumes/ | macOS only |
| `scan_photos_library.py` | Photos.sqlite 读取 | macOS only |
| `quick_scan.py` | Photos.sqlite 读取 | macOS only |

`move_to_trash()` 在非 macOS 上运行将静默失败（osascript 不存在）。

**建议修复**: 对 macOS 专有功能添加平台检测（`sys.platform == "darwin"`），非 macOS 提供降级方案或明确报错。`move_to_trash()` 可使用 `send2trash` 库作为跨平台替代。

---

### C-02 `__import__("re")` 内联导入 — `scan_photos.py:122`

**严重性: P2**

```python
IOS_SCREENSHOT_RE = __import__("re").compile(r"^IMG_\d+\.PNG$", __import__("re").IGNORECASE)
```

模块级使用 `__import__()` 而非正常 import 语句，违反 PEP 8 和可读性规范，且在某些打包工具中可能导致问题。

**建议修复**: 在文件顶部添加 `import re`，然后使用 `re.compile(...)`。

---

### C-3 隐式编码假设 — `find_exact_duplicates.py:146`

**严重性: P2**

```python
with open(output_path, "w", encoding="utf-8") as f:
```

大多数文件输出使用 `utf-8-sig`（BOM），但此处使用 `utf-8`。不一致可能导致 CSV 文件在不同工具中的兼容性问题。

**建议修复**: 统一使用 `utf-8-sig` 编码写入 CSV 文件。

---

## 6. API Consistency (API 一致性)

### A-01 `find_duplicates_db()` 返回类型不一致 — `find_exact_duplicates.py:19` vs `organize_photos.py:183`

**严重性: P1**

`find_exact_duplicates.py:find_duplicates_db()` 返回 `tuple(list, dict)`:
```python
return duplicates, group_meta
```

`organize_photos.py:183` 直接将其结果作为列表使用:
```python
exact_results = find_duplicates_db(index_db)
if exact_results:
    for r in exact_results:
        r["match_type"] = "exact_sha256"
```

此处 `exact_results` 实际是 `(list, dict)` 元组，迭代元组会遍历列表和字典，而非列表中的单个条目。这会导致 `r["match_type"]` 对 `group_meta` 字典抛出 `TypeError`。

**建议修复**: 解包返回值：`exact_results, group_meta = find_duplicates_db(index_db)`。

---

### A-02 CLI 参数命名不一致 — 多文件

**严重性: P2**

| 脚本 | 参数 | 含义 |
|------|------|------|
| `scan_photos.py` | `--input` | 输入目录 |
| `scan_photos_library.py` | `--library` | 输入库路径 |
| `quick_scan.py` | `--input` / `--library` | 输入路径 |
| `find_similar_photos.py` | `--index` | 索引路径 |
| `find_exact_duplicates.py` | `--index` | 索引路径 |
| `generate_move_plan.py` | `--duplicates` / `--index` | 输入路径 |
| `generate_preview.py` | `--duplicates` / `--index` | 输入路径 |
| `import_to_photos.py` | `--source` / `--library` | 输入路径 |
| `organize_photos.py` | `--source` | 输入路径 |
| `apply_move_plan.py` | `--plan` | 输入路径 |

输入路径的参数名有 `--input`, `--library`, `--index`, `--duplicates`, `--source`, `--plan` 六种不同命名。

**建议修复**: 统一命名：数据库索引路径用 `--index`，目录路径用 `--input`，计划文件用 `--plan`。

---

### A-03 `read_duplicates()` 返回类型文档不准确 — `generate_move_plan.py:27`

**严重性: P2**

```python
def read_duplicates(dups_path: str) -> dict:
    """Read duplicates CSV, return {group_id: [file_path, ...]}."""
```

实际返回 `(groups_dict, match_types_dict)` 元组，而非单个 dict。类型注解和文档字符串均不正确。

**建议修复**: 修改类型注解为 `-> tuple[dict, dict]`，更新文档字符串。

---

### A-04 重复的 `compute_sha256` / EXIF 函数 — `scan_photos.py` vs `scan_photos_library.py`

**严重性: P2**

两个文件中完全重复的函数：
- `compute_sha256()` — 实现完全相同
- `get_exif_datetime()` — 实现完全相同
- `get_gps_coords()` — 实现完全相同
- `get_camera_info()` — 实现完全相同
- `has_exif_data()` — 实现完全相同
- `compute_phash()` — 实现完全相同
- `get_image_size()` — 实现完全相同
- `get_format_family()` — 实现完全相同
- `compute_aspect_ratio()` — 实现完全相同
- `get_subsec_time()` — 实现完全相同
- `IMAGE_EXTS` / `VIDEO_EXTS` — 完全相同

`quick_scan.py` 中又重复了 `compute_sha256()` 和 `get_format_family()`。

**建议修复**: 提取到共享模块 `utils.py`，各脚本通过 `from utils import ...` 引用。

---

## 问题汇总

| 严重性 | 数量 | 类别分布 |
|--------|------|----------|
| **P0** | 4 | Security: 4 (S-01 ~ S-04) |
| **P1** | 11 | Security: 1, Error: 6, Logic: 1, Performance: 3, API: 1 |
| **P2** | 14 | Security: 2, Error: 2, Logic: 4, Performance: 4, Compatibility: 3, API: 3 |

### 按文件统计

| 文件 | P0 | P1 | P2 | 总计 |
|------|----|----|-----|------|
| `apply_move_plan.py` | 1 | 2 | 1 | 4 |
| `import_to_photos.py` | 3 | 0 | 2 | 5 |
| `scan_photos.py` | 0 | 1 | 2 | 3 |
| `scan_photos_library.py` | 0 | 2 | 1 | 3 |
| `generate_preview.py` | 0 | 2 | 1 | 3 |
| `organize_photos.py` | 0 | 3 | 1 | 4 |
| `find_exact_duplicates.py` | 0 | 2 | 1 | 3 |
| `find_similar_photos.py` | 0 | 0 | 3 | 3 |
| `generate_move_plan.py` | 0 | 0 | 2 | 2 |
| `quick_scan.py` | 0 | 2 | 1 | 3 |

### 优先修复建议

1. **立即修复 (P0)**: S-01 ~ S-04 四处 AppleScript 注入漏洞
2. **尽快修复 (P1)**: A-01 返回类型不一致（运行时 TypeError）、E-07 空 sha256 分组、E-02/E-03 资源泄漏、P-01~P-03 逐行 COMMIT
3. **计划修复 (P2)**: 代码去重（A-04）、统一 API 命名（A-02）、性能优化（P-06/P-07）

---

## 已修复问题（2026-06-16）

### 已修复 P0 问题

| 编号 | 问题 | 修复方式 |
|------|------|----------|
| S-01 | `apply_move_plan.py` AppleScript 注入 | 已在早期修复 |
| S-02~S-04 | `import_to_photos.py` AppleScript 注入 (3处) | 添加 `_escape_applescript()` 函数，对所有用户可控字符串转义 |

### 已修复 P1 问题

| 编号 | 问题 | 修复方式 |
|------|------|----------|
| A-01 | `organize_photos.py` tuple unpacking | `find_duplicates_db()` → `find_duplicates_db()` 改为解包 `exact_results, _ = ...` |
| — | `find_similar_photos.py` IMAGEHASH_AVAILABLE 缺失 | `detect_scaled_duplicates_db()` 和 `detect_cross_format_duplicates_db()` 添加依赖检查 |
| — | `scan_photos.py` 硬退出 | 改为优雅降级：PILLOW_AVAILABLE / PIEXIF_AVAILABLE / IMAGEHASH_AVAILABLE 标志位 + 启动警告 |
| — | `generate_move_plan.py` / `generate_preview.py` 缺少 match type labels | 添加 `exact_sha256`、`apple_quality_vector`、`cnn_mobilenet` 标签 |

### 已修复 P2 问题

| 编号 | 问题 | 修复方式 |
|------|------|----------|
| — | scaled/cross-format 使用 visited-set | 改为 union-find 算法，处理传递性相似链 |
| — | DB 列不存在时崩溃 | 所有检测函数添加 `PRAGMA table_info` 列存在性检查 + `try/except OperationalError` |

### 新增功能

| 功能 | 描述 |
|------|------|
| **隐私风险评估** | `detect_privacy_risks.py` — 检测身份证、银行卡、护照等敏感文档，支持 JSON/CSV/文本报告 |
| **CNN 深度学习去重** | `find_similar_photos.py` 新增 `--detect-cnn` 模式，MobileNet-V3 特征提取，PyTorch/ONNX 双后端优雅降级 |

### 误报修复（2026-06-16 第二轮）

| 问题 | 原因 | 修复方式 |
|------|------|----------|
| pHash 全零哈希分组 | 小图标/纯色图产生 `0000000000000000`，导致不相关文件分在一组 | SQL 查询和 Python 层双重过滤全零 phash |
| pHash 低熵哈希分组 | 1-3 位 set bits 的 phash（如 `8000000000000000`）信息量不足 | 新增 `_is_low_entropy_phash()` 函数，过滤 bits < 4 或 > 60 的哈希 |
| Cross-format 误报 | 仅靠 aspect ratio + dimensions + phash 就把不同内容的 HEIC/JPEG 分组 | 添加文件大小比率检查（>8x 差异视为不同内容） |
| Scaled 误报 | 缩放检测中 bytes-per-pixel 差异极大的图像被分在一组 | 添加 bpp 比率检查（>8x 差异视为不同内容） |
| Cross-format 阈值过严 | 5.0x 文件大小比率阈值把 PNG/JPEG 同内容对过滤掉 | 放宽至 8.0x（PNG 无损压缩可比 JPEG 小 5-6 倍） |
| `_is_scaled_pair` 同尺寸 bug | 800x1200 vs 800x1200 被当作"1x缩放"通过检测 | 添加 `w1==w2 and h1==h2` 前置检查，同尺寸直接返回 False |
| 小图标 phash 误报 | 16x16 图标产生有意义的 phash 但匹配无实际意义 | 新增 `PHASH_MIN_PIXELS=1024` 阈值，SQL + Python 双层过滤 |

### 误报修复（2026-06-16 第四轮）

| 问题 | 原因 | 修复方式 |
|------|------|----------|
| `_is_scaled_pair` ratio 归一化 bug | `ratio = min(rw, rh)` 对小图→大图方向得到 ratio < 1.0，但简单分数检查只匹配 ≥ 1.0（`denom/numer` 且 `numer ≤ denom`），导致2x缩放识别失败 | 改为 `ratio = max(rw, rh)` + `< 1.0` 时取倒数，确保 ratio ≥ 1.0 |
| Scaled union-find 传递性误报 | 不同照片通过 "hub" 图像被传递性链接（A↔Hub↔C → A和C同组） | 改用 pair-collection + selective union，仅 union dist ≤ 3 的对（SCALED_UNION_THRESHOLD=3） |
| Cross-format union-find 传递性误报 | 与 scaled 相同的传递链问题（PNG↔JPEG_A + PNG↔JPEG_B → A、B同组） | 改用 pair-collection + selective union，仅 union dist ≤ 1 的对（near-exact match） |
| Cross-format 阈值过松 | `CROSS_FORMAT_PHASH_THRESHOLD=12` 允许太多误匹配 | 降至 5（同一照片不同格式 phash 差异通常 ≤ 2） |
| Cross-format 文件大小比率 | 5x→8x→10x 逐步放宽，PNG 无损可比 JPEG 大 5-6 倍 | 最终设为 10.0x |
