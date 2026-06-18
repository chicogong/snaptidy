# SnapTidy

[English](README.md) | 简体中文

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/Platform-macOS-black.svg?style=flat-square)](https://www.apple.com/macos)
[![AI Skill](https://img.shields.io/badge/AI-Skill-purple.svg?style=flat-square)](https://github.com/topics/ai-skill)
[![CI](https://img.shields.io/github/actions/workflow/status/chicogong/snaptidy/ci.yml?branch=main&label=CI&style=flat-square)](https://github.com/chicogong/snaptidy/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/Version-3.14.0-green.svg?style=flat-square)](https://github.com/chicogong/snaptidy)
[![Website](https://img.shields.io/badge/Website-realtime--ai.chat-blue.svg?style=flat-square)](https://realtime-ai.chat/snaptidy/)

> macOS 照片视频整理去重工具。通过感知哈希 (pHash)、Apple ML 特征向量和 SHA-256 检测重复照片，支持跨格式去重（HEIC↔JPEG）、EXIF 修复、GPS 逆地理编码。AI 对话驱动，只读扫描，人工确认后操作，零风险。开源免费 (MIT)。

<p align="center">
  <img src="https://realtime-ai.chat/snaptidy/screenshots/landing-page.png" alt="SnapTidy 着陆页" width="800">
</p>

## SnapTidy 功能对比

| 功能 | SnapTidy | 商业软件 | 基础 CLI 工具 |
|------|----------|---------|--------------|
| AI 对话驱动 | ✓ | ✗ | ✗ |
| 零安装核心（仅标准库） | ✓ | ✗ | ~ |
| 感知哈希 (pHash) 相似检测 | ✓ | ~ | ~ |
| Apple ML 特征向量检测 | ✓ | ✗ | ✗ |
| 跨格式去重（HEIC ↔ JPEG） | ✓ | ~ | ✗ |
| 缩放去重（不同分辨率同一照片） | ✓ | ✗ | ✗ |
| 连拍检测（SubSecTime） | ✓ | ✗ | ✗ |
| EXIF 元数据提取与编辑 | ✓ | ~ | ✗ |
| GPS 逆地理编码 | ✓ | ✗ | ✗ |
| 隐私风险检测（身份证/护照/银行卡） | ✓ | ✗ | ✗ |
| iCloud 占位文件处理 | ✓ | ✗ | ✗ |
| 视频去重 | ✓ | ~ | ✗ |
| Live Photo 保护 | ✓ | ~ | ✗ |
| Google Takeout 导入 | ✓ | ✗ | ✗ |
| 质量评估（模糊/亮度/对比度） | ✓ | ~ | ✗ |
| macOS 废纸篓恢复 | ✓ | ~ | ✗ |
| 免费开源 | ✓ | ✗ | ~ |

## 目录

- [SnapTidy 功能对比](#snaptidy-功能对比)
- [为什么选择 SnapTidy？](#为什么选择-snaptidy)
- [新功能](#v313-新功能)
- [核心特性](#核心特性)
- [安装](#安装)
- [工作原理](#工作原理)
- [安全保证](#安全保证)
- [快速开始](#快速开始)
- [智能优先级规则](#智能优先级规则)
- [自动分类](#自动分类15-语言)
- [存储与性能](#存储与性能)
- [支持的格式](#支持的格式)
- [脚本参考](#脚本参考)
- [依赖](#依赖)
- [平台兼容性](#平台兼容性)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

## 为什么选择 SnapTidy？

你的照片库增长很快 — iPhone 拍摄、iCloud 导出、安卓传输、微信保存、旧备份和截图日积月累。现有工具如 [Sorty](https://github.com/nicoschmdt/sorty)、[Tidy](https://github.com/nicoschmdt/tidy) 和 [Hazelnut](https://github.com/josephearl/hazelnut) 是需要安装配置的独立应用。**SnapTidy 采用不同方式**：它是一个 AI 助手技能，你用自然语言描述需求，它自动处理。

**iPhone 用户**：整理照片不需要 iCloud 同步到电脑。通过 USB 连接 iPhone，SnapTidy 可以直接扫描 Photos.app 图库，或者先用 Finder 将照片同步到本地文件夹。使用 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) 等工具还可以直接通过 USB 访问 iPhone 的 DCIM 目录，无需 iCloud。

核心区别？**安全第一，零风险。** SnapTidy 永不删除任何东西。它以只读方式扫描，生成人类可读的计划，仅在明确批准后移动文件 — 可选移至 macOS 废纸篓（通过 Finder 恢复）。

## v3.14 新功能

| 功能 | 说明 |
|---------|-------------|
| 🔍 **扩展名校验** | `detect_bad_extensions.py` — 检测文件内容（magic bytes）与扩展名不匹配的文件（如 JPEG 内容用 `.png` 扩展名）；支持 20+ 种格式签名；`--parallel`、`--incremental`、`--report` |
| 📊 **7 维质量评分** | `assess_quality.py` 从 3 维升级到 7 维：锐度、曝光、对比度、分辨率、格式质量、文件大小效率、EXIF 完整度；加权综合评分让去重决策更智能 |
| 📝 **SKILL.md 精简** | 从 436 行精简到 91 行；详细功能表移至 `references/features.md`；描述缩短为 3 句话 |
| 🔧 **CI 持续集成** | `.github/workflows/ci.yml` — 每次 PR/push 自动检查 42 个脚本语法 + 集成测试 |

## v3.13 新功能

| 功能 | 说明 |
|------|------|
| 🔄 **批量 EXIF 方向纠正** | `rotate_photos.py` — 检测 EXIF Orientation 标记，物理旋转像素到正确方向，重置 Orientation 为 1；支持 `--dry-run`、`--orientation N` 过滤 |
| 🖼️ **格式转换** | `convert_format.py` — JPEG/HEIC/PNG → WEBP/AVIF，保留 EXIF 元数据，30-50% 空间节省；`--dry-run` 预估节省量 |
| 📍 **GPS 邻近推断** | `fix_gps.py` — 从时间相邻的照片推断缺失 GPS（±10 分钟窗口），可选写入 EXIF |
| 🎬 **动图检测** | `is_animated_image()` — 检测 GIF/animated WebP/APNG，新增 `is_animated` 数据库列 |
| 🛡️ **解压缩炸弹防护** | `Image.MAX_IMAGE_PIXELS` 设为 60MP，防止恶意超大图 OOM |
| 📱 **AVIF 格式支持** | 完整 AVIF 解码支持（Pillow ≥11 原生或 `pillow-avif-plugin`） |

## v3.12 新功能

| 功能 | 说明 |
|------|------|
| ☁️ **iCloud 优化存储处理** | 三种模式：`--warn-icloud`（默认，扫描但标记）、`--skip-icloud`（跳过占位文件）、`--download-icloud`（触发 `brctl download` 下载后扫描）；通过 `.icloud` 伴生文件、扩展属性、大小启发式检测缩略图 |
| 🔍 **iCloud 检查脚本** | `check_icloud.py` — 独立工具：扫描目录检测 iCloud-only 文件，报告数量/大小/预估下载空间，批量下载带进度，验证所有文件已本地化 |
| 🧹 **下游脚本 iCloud 过滤** | `find_exact_duplicates.py --exclude-icloud` 和 `find_similar_photos.py --exclude-icloud` — 去重时跳过不可靠的 iCloud 占位文件哈希/pHash |
| 📊 **增强库健康报告** | `library_stats.py` 新增 iCloud 详细状态：占位文件数、已下载数、下载失败数 — 终端和 HTML 报告均显示 |
| 📦 **共享 iCloud 模块** | `icloud_utils.py` — 整合 `check_icloud_status()`、`download_icloud_file()`、`is_likely_thumbnail()`、`batch_download()` 为单一可复用模块 |

<details>
<summary>旧版本 (v3.8 – v3.11)</summary>

### v3.11

| 功能 | 说明 |
|------|------|
| 🏗️ **统一扩展名定义** | 所有格式集合归入 `constants.py`；新增 AVIF、WebM、MTS、ORF、RW2 等；点号前缀变体用于直接后缀比较 |
| ⚡ **并行扫描** | `scan_photos.py --parallel 4` — 2.9 倍提速；`assess_quality.py --parallel 4` — 线程池质量评估 |
| 🔄 **增量扫描** | `scan_photos.py --incremental` — 跳过未变文件；二次运行快 35 倍（0.1s vs 3.4s） |
| 🚀 **pHash 性能优化** | 前缀索引预过滤取代 O(n²) 两两比较；支持 5 万+ 照片库 |
| 🗜️ **照片压缩** | `compress_photos.py` — 按分辨率分层智能 JPEG 压缩；PNG→JPEG 转换；预览模式；安全备份 |
| 📅 **时间线空白检测** | `timeline_gaps.py` — 检测异常日期空白（可能丢失照片）；自适应阈值；严重程度分类 |

### v3.10

| 功能 | 说明 |
|------|------|
| 💥 **损坏文件检测** | `detect_corrupted.py` — 检测损坏/截断的图片和无法播放的视频；Pillow 多层验证 + ffmpeg 探测；并行处理 |
| 📅 **照片日期修正** | `fix_dates.py` — 从文件名模式（15+ 种）、相邻照片、文件修改时间推断并修复缺失的 EXIF 日期 |
| 🔄 **备份验证** | `verify_backup.py` — 验证备份完整性；快速模式（文件名+大小）和完整模式（SHA-256，识别重命名）；覆盖率报告 |
| 📂 **重复文件夹检测** | `find_duplicate_folders.py` — 按内容哈希找出完全或高度相似的文件夹；Jaccard 相似度 |
| 💡 **空间假设分析** | `library_stats.py --what-if` — "如果删除所有截图/重复/RAW/低质量文件能省多少空间？" |
| 📋 **事件相册创建** | `organize_photos.py --create-event-albums` — 从事件聚类结果自动创建 Photos.app 相册 |

### v3.9

| 功能 | 说明 |
|------|------|
| 🎯 **照片质量评估** | `assess_quality.py` — 模糊/亮度/对比度/质量评分(0-100)，集成到去重策略和审核页面 |
| 🎵 **Live Photo 识别** | `detect_live_photos.py` — 识别 HEIC+MOV 配对，去重时保持 Live Photo 完整 |
| 📷 **RAW 孤儿清理** | `find_orphan_raw.py` — 找到无 JPEG 伴侣的 RAW 文件 |
| 📅 **时间线视图** | `generate_timeline.py` — 交互式 HTML 时间线，按年/月/日缩放，分类筛选 |
| 🔄 **跨库对比** | `compare_libraries.py` — Photos.app vs 文件系统，按 SHA-256 找独有和共有照片 |
| 📥 **Google Takeout 导入** | `import_google_takeout.py` — 导入 Google Photos 导出，合并 JSON 元数据到 EXIF |
| 🗺️ **GPX 地理标注** | `gpx_geotag.py` — 从 GPX 轨迹文件给无 GPS 的照片补上位置信息 |
| 📊 **事件聚类** | `cluster_events.py` — 按时间+地点自动分组为"事件" |
| 🎬 **视频去重** | `find_similar_videos.py` — 视频帧采样 + 感知哈希检测重复视频 |
| ✏️ **智能重命名** | `rename_photos.py` — 按 EXIF 日期/相机/地点重命名 |

### v3.8

| 功能 | 说明 |
|------|------|
| 📍 **逆地理编码** | GPS → 地名（城市/地区/国家），支持 CoreLocation（离线）、Locationator、Nominatim 三种后端；持久化 JSON 缓存 |
| ✏️ **EXIF 编辑** | 移除 GPS、设置日期、写入标签 — `edit_exif.py` 带备份/恢复 + `--dry-run` 安全机制 |
| 🌍 **按地点整理** | `--mode by-location` 将照片整理到 `国家/地区/城市/` 文件夹结构 |
| 📊 **地点统计** | `library_stats.py` 现在显示按城市统计的照片数量（终端 + HTML 报告） |
| 📋 **交互式审核** | `generate_review.py` — HTML 审核页面，智能策略规则（元数据/最早/最新/分辨率/偏好相册），相册展示，收藏保护 |
| 🔍 **隐私风险检测** | `detect_privacy_risks.py` — 查找敏感文档（身份证、银行卡、护照、密码）基于文件名/文件夹/分类/尺寸启发式 |

</details>

<details>
<summary>v3.7</summary>

| 功能 | 说明 |
|------|------|
| 📊 **照片库健康与洞察** | 新增只读 `library_stats.py`（及 `--mode stats`）— 总量、类别/格式/年度分布、健康指标（截图、无 EXIF、GPS、仅 iCloud、可能模糊、收藏）、占空间最大文件。支持终端 / JSON / HTML 输出 |
| 🧩 **公共模块重构** | 抽取 `photo_metadata.py`、`constants.py`、`applescript_utils.py` — 消除约 600 行重复的 EXIF/哈希/格式代码（单一真相源） |
| 🎛️ **CLI 标准化** | 统一所有脚本参数 — `--source` / `--index`（`-i`）/ `--output`（`-o`），旧的 `--input`/`--library` 作为向后兼容别名保留 |
| 🔁 **前后对比报告** | `--mode photos-album` 的 HTML 报告新增新建/变更/未变相册及照片数量增量对比（支持 `--dry-run`） |
| 🐛 **关键 Bug 修复** | 相册分隔符契约、回收站 AppleScript 注入、共享流程 NameError、整理器与报告间 emoji 不一致 |

<details>
<summary>v3.4</summary>

| 功能 | 说明 |
|------|------|
| 🧠 **Apple 质量向量检测** | 零依赖相似度检测，利用 Apple 预计算的 17 维 ML 特征向量（`ZCOMPUTEDASSETATTRIBUTES`） |
| 📦 **可选依赖** | Pillow、piexif、imagehash 现为可选 — 核心功能仅需 Python 标准库 |
| 👥 **半自动共享相册** | `--share-to-album` 标记并选中照片，你只需拖到共享相册（1 步操作） |
| 📚 **精简 SKILL.md** | SKILL.md 缩减至 ≤65 行，详情移至 `references/` 目录（检测、导入、性能、优先级规则、故障排除） |
| 🔧 **Union-Find 分组** | Apple QL 检测使用 union-find 算法，正确处理传递性相似分组 |

</details>

<details>
<summary>v3.3</summary>

| 功能 | 说明 |
|------|------|
| 📱 **导入 Photos.app** | 从外置硬盘/安卓导入并自动去重 |
| 👥 **共享相册读取** | 从 Photos.sqlite 读取共享相册信息 |
| ☁️ **iCloud 同步感知** | 检测仅存 iCloud 的文件和下载状态 |
| 🔄 **断点续传** | 导入流程支持中断后续传 |
| 💾 **零数据丢失** | 流式 SQLite 写入 — 逐条即时提交 |

</details>

## 核心特性

- 🎯 **SHA-256 精确去重** — 在整个图库中查找字节完全相同的重复文件
- 👁️ **感知哈希相似度** — 使用 pHash 检测视觉相同的图像，支持模糊汉明距离阈值
- 🧠 **Apple 质量向量检测** — 零依赖相似度检测，利用 Apple 预计算的 17 维 ML 向量（`--detect-apple-ql`）
- 🔀 **跨格式去重** — 同一照片的 HEIC 和 JPEG 版本
- 📐 **缩放去重** — 同一照片不同分辨率
- 📸 **连拍检测** — 通过 SubSecTime 分组连拍照片
- 📋 **丰富元数据索引** — 提取文件大小、EXIF 日期、GPS、相机信息、**地名（城市/地区/国家）**等写入 SQLite 或 CSV
- 📍 **逆地理编码** — 将 GPS 坐标转换为地名（CoreLocation/Nominatim），持久化缓存
- ✏️ **EXIF 编辑** — 移除 GPS、设置日期、写入标签，带备份/恢复安全机制
- 🌍 **按地点整理** — 将照片整理到 `国家/地区/城市/` 文件夹结构
- 🔍 **隐私风险检测** — 查找敏感文档（身份证、银行卡、护照、密码、医疗记录）基于文件名/文件夹/分类/尺寸启发式
- 📋 **交互式审核** — HTML 审核页面，智能策略规则（元数据/最早/最新/分辨率/偏好相册/画质），相册展示，收藏保护
- 🎯 **照片质量评估** — 模糊/亮度/对比度评分，集成到去重策略和审核
- 🎵 **Live Photo 识别** — 去重时保持 Live Photo 配对完整
- 📷 **RAW 孤儿清理** — 找到无 JPEG 伴侣的 RAW 文件
- 📅 **时间线视图** — 交互式 HTML 时间线，缩放和分类筛选
- 🔄 **跨库对比** — Photos.app vs 文件系统，按 SHA-256 找独有和共有照片
- 📥 **Google Takeout 导入** — 导入 Google Photos 导出，合并元数据
- 🗺️ **GPX 地理标注** — 从 GPX 轨迹文件给照片补位置
- 📊 **事件聚类** — 按时间+地点自动分组
- 🎬 **视频去重** — 视频帧采样 + 感知哈希
- ✏️ **智能重命名** — 按 EXIF 元数据重命名
- 🛡️ **安全优先设计** — 只读扫描、仅移动操作、废纸篓模式、CSV 审计跟踪
- 💾 **零数据丢失** — 流式 SQLite 写入，逐条提交
- 💬 **对话驱动** — 通过 AI 助手交互，无需 GUI 或配置文件
- ⚡ **零配置** — 指向目录即可开始
- 🔌 **多平台** — 兼容 Claude Code、Cursor、Windsurf、WorkBuddy 等
- 🗄️ **可扩展** — SQLite 后端处理 10 万+ 照片
- 📦 **零安装核心** — 所有可选依赖优雅降级；核心功能（SHA-256、Apple QL、元数据）仅需 Python 标准库

## 安装

### 方式一：一句话安装（推荐）

告诉你的 AI 助手：

> 安装此技能：https://github.com/chicogong/snaptidy

### 方式二：命令行安装

```bash
# 兼容 45+ AI 平台
npx skills add chicogong/snaptidy

# 或通过 ClawHub
clawhub install snaptidy
```

### 方式三：手动安装

<details>
<summary>Claude Code</summary>

```bash
git clone https://github.com/chicogong/snaptidy.git ~/.claude/skills/snaptidy
cd ~/.claude/skills/snaptidy && pip install -r requirements.txt
```
</details>

<details>
<summary>Cursor</summary>

```bash
git clone https://github.com/chicogong/snaptidy.git
cp -r snaptidy/.cursor/rules/snaptidy.mdc .cursor/rules/
```
</details>

<details>
<summary>WorkBuddy</summary>

```bash
git clone https://github.com/chicogong/snaptidy.git ~/.workbuddy/skills/snaptidy
cd ~/.workbuddy/skills/snaptidy && pip install -r requirements.txt
```
</details>

## 工作原理

![SnapTidy Pipeline](assets/pipeline.svg)

1. **扫描** — 遍历照片/视频目录，提取元数据（大小、SHA-256、EXIF 日期、GPS、相机信息、尺寸、感知哈希、自动分类、文件夹标签），写入 SQLite（推荐）或 CSV
2. **查找重复** — 按精确哈希（SHA-256）和感知哈希（pHash）分组，支持模糊阈值
3. **审核** — 交互式 HTML 页面，并排浏览重复项，应用智能策略规则，标记保留/移除
4. **生成计划** — 智能多因素评分决定保留哪张，支持可配置策略和文件夹偏好
5. **执行** — 确认 CSV 计划后执行，可选移至文件夹或废纸篓（可恢复）
6. **撤销** — 30 天内可撤销最近一次移动操作

## 安全保证

| 保证 | 如何实现 |
|------|----------|
| 无自动删除 | 所有脚本默认只读，`apply_move_plan.py` 只移动文件 |
| macOS 废纸篓模式 | 使用 `--mode trash` 移至废纸篓，可通过 Finder 恢复 |
| 需人工审核 | 移动计划为 CSV 文件，可用电子表格查看 |
| 完整审计跟踪 | 每次移动都记录到 `move_log.csv`，含源、目标、状态和原因 |
| 零数据丢失 | 流式 SQLite 逐条写入，崩溃最多丢失一条记录 |
| 跳过已存在文件 | 目标文件已存在则自动跳过 |
| Photos Library 保护 | 永不进入 `.photoslibrary` 和 `.photolibrary` 目录 |
| 备份感知 | 自动跳过 `Original_Backup`、`.trashes` 等目录 |
| 智能优先级 | 多因素评分确保始终保留最佳质量照片 |

## 快速开始

### 前提条件

- **macOS**（测试于 macOS 13+）
- **Python 3.9+**
- **完全磁盘访问权限**已为终端启用（系统设置 → 隐私与安全性 → 完全磁盘访问权限）

### 使用方法

告诉你的 AI 助手你想要什么：

> *"扫描 /Volumes/Photos 下的照片库并查找重复项"*

或直接运行脚本：

```bash
# 第 1 步：扫描（大型图库推荐 SQLite，逆地理编码默认开启）
python3 scripts/scan_photos.py --source /path/to/your/photos --output ./photo_index.db

# 第 1b 步：不进行逆地理编码的扫描（更快，无地名数据）
python3 scripts/scan_photos.py --source /path/to/your/photos --output ./photo_index.db --no-geocode

# 第 1c 步：快速扫描（零安装，无需任何依赖）
python3 scripts/quick_scan.py --source /path/to/your/photos --output ./photo_index.db --dedup

# 第 1d 步（可选）：照片库健康与洞察（只读）
python3 scripts/library_stats.py --index ./photo_index.db
python3 scripts/library_stats.py -i ./photo_index.db --report ./health.html

# 第 2 步：查找精确重复
python3 scripts/find_exact_duplicates.py --index ./photo_index.db --output ./duplicates_exact.csv
python3 scripts/find_exact_duplicates.py --index ./photo_index.db --output ./dups.txt --format human

# 第 3 步（可选）：查找感知相似图像
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./duplicates_similar.csv
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --detect-all

# 第 3b 步（可选）：使用 Apple 零依赖 ML 向量查找相似照片
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar_apple.csv --detect-apple-ql
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar_apple.csv --detect-apple-ql --apple-ql-threshold 0.95

# 第 4 步：生成智能移动计划
python3 scripts/generate_move_plan.py \
    --duplicates ./duplicates_exact.csv \
    --index ./photo_index.db \
    --plan ./move_plan.csv \
    --target-root /path/to/your/photos \
    --prefer-folder "DCIM" --strategy quality

# 第 5 步：HTML 缩略图预览（可选但推荐）
# 可使用第 2 步的 duplicates_exact.csv 或第 3 步的 duplicates_similar.csv
python3 scripts/generate_preview.py \
    --duplicates ./duplicates_similar.csv \
    --index ./photo_index.db \
    --output ./preview.html

# 第 6 步：审核移动计划后执行
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --mode trash

# 第 7 步：如需撤销
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --undo
```

<p align="center">
  <img src="https://realtime-ai.chat/snaptidy/screenshots/preview-duplicates.png" alt="SnapTidy 去重预览" width="700">
  <em>HTML 缩略图预览 — 操作前可先审查</em>
</p>

### 导入 Photos.app

```bash
# 干运行：预览导入内容
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --dry-run

# 导入所有唯一照片（自动跳过重复）
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --album "Vacation 2025"

# 从安卓 DCIM 导入
python3 scripts/import_to_photos.py --source /Volumes/Android/DCIM --album "Android Import"

# 半自动共享相册工作流（1 步手动拖拽）
python3 scripts/import_to_photos.py --source /Volumes/External/Photos \
    --album "Vacation 2025" \
    --share-to-album "Vacation 2025"

# 列出共享相册（只读）
python3 scripts/import_to_photos.py --show-shared-albums
```

### 一键交互式流程

```bash
# 交互模式 — 逐步询问偏好
python3 scripts/organize_photos.py --source ~/Pictures/Export --interactive

# 非交互式干运行
python3 scripts/organize_photos.py \
    --source ~/Pictures/Export --dedup-method all \
    --strategy quality --trash-mode trash --dry-run

# 按日期整理到 YYYY/MM 文件夹
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-date --dry-run

# 按分类整理（01_Photos, 02_Screenshots, 03_WeChat 等）
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-category --dry-run

# 按地点整理（国家/地区/城市/文件名）
python3 scripts/organize_photos.py --source ~/Pictures/Export --mode by-location --dry-run

# 检测已连接的安卓设备和外置硬盘
python3 scripts/organize_photos.py --source /any --detect-sources
```

### 逆地理编码

```bash
# 查询单个 GPS 坐标的地名
python3 scripts/reverse_geocode.py --lat 39.9042 --lon 116.4074

# 指定后端和语言
python3 scripts/reverse_geocode.py --lat 37.7749 --lon -122.4194 --backend nominatim --lang en

# 设置自定义缓存目录
python3 scripts/reverse_geocode.py --lat 31.2304 --lon 121.4737 --cache-dir ./geocache
```

### 交互式审核

在删除前审核重复项 — **永不直接操作文件**，仅记录你的决定：

```bash
# 生成交互式审核页面
python3 scripts/generate_review.py \
    --index ./photo_index.db \
    --duplicates ./duplicates_exact.csv \
    --similar ./duplicates_similar.csv \
    --output ./review.html

# 在浏览器中打开 review.html，标记保留/移除，导出决策 CSV
```

**智能策略规则**（一键应用到所有分组）：
| 策略 | 保留 | 适用于 |
|------|------|--------|
| 元数据最全 | EXIF/相机/GPS/日期完整度最高的 | 保留信息最丰富的版本 |
| 日期最早 | 最早拍摄日期 | 保留原始照片 |
| 日期最新 | 最近修改日期 | 保留最终编辑 |
| 分辨率最高 | 最大像素尺寸 | 保留最清晰的版本 |
| 偏好相册 | 来自指定相册的照片 | 保留你喜欢的相册中的照片 |

⭐ 收藏照片永不会被自动标记为删除。

### 隐私风险检测

查找不应出现在照片库中的敏感文档：

```bash
# 扫描隐私风险（自动根据扩展名判断格式）
python3 scripts/detect_privacy_risks.py --index ./photo_index.db --output ./privacy_report.txt

# JSON 格式（用于脚本处理）
python3 scripts/detect_privacy_risks.py --index ./photo_index.db --output ./privacy_report.json

# CSV 格式（用于电子表格查看）
python3 scripts/detect_privacy_risks.py --index ./photo_index.db --output ./privacy_report.csv

# 仅显示高风险及以上
python3 scripts/detect_privacy_risks.py --index ./photo_index.db --output ./report.txt --min-risk high
```

**检测方法**：文件名模式（身份证、护照、银行卡、密码）、文件夹路径分析、分类+关键词匹配（金融应用截图）、尺寸启发式（卡片形状图像）。

### EXIF 编辑

```bash
# 从索引中移除所有照片的 GPS 数据（先干运行！）
python3 scripts/edit_exif.py strip-gps --index ./photo_index.db --dry-run

# 实际移除 GPS 数据
python3 scripts/edit_exif.py strip-gps --index ./photo_index.db

# 仅移除有 GPS 数据的照片
python3 scripts/edit_exif.py strip-gps --index ./photo_index.db --only-gps

# 设置指定文件的 EXIF 日期
python3 scripts/edit_exif.py set-date --date "2025-06-15T14:30:00" --paths photo1.jpg photo2.heic

# 写入标签/关键词到指定文件
python3 scripts/edit_exif.py set-tags --tags "vacation,beach,summer" --paths photo1.jpg photo2.jpg
```

## 智能优先级规则

决定保留哪张重复照片时，SnapTidy 按以下因素评分：

| 因素 | 权重 | 理由 |
|------|------|------|
| 分辨率（像素） | 高（0–100） | 更高分辨率 = 更好质量 |
| 文件大小 | 中（0–50） | 更大 = 压缩更少 |
| EXIF 完整性 | 高（+30） | 有元数据 = 可能是原图 |
| 格式（RAW +20, HEIC +10） | 中 | 更好格式 = 更好质量 |
| 分类（照片 +15, 截图 -20, 微信 -10） | 中 | 真实照片优先于截图 |
| 文件夹偏好 | 可配置（+50） | 用户指定的优先文件夹 |
| Photos.app 收藏 | 高（+50） | 绝不移动收藏照片 |

**策略**（`--strategy`）：`quality`（默认）、`oldest`、`newest`、`folder`

## 自动分类（15+ 语言）

| 分类 | 检测方式 |
|------|----------|
| 照片 | 相机照片默认分类 |
| 截图 | "screenshot"、"截图"、"截屏"、"スクリーンショット"、"스크린샷"、"скриншот" |
| 微信 | "mmexport"、"wx_camera_"、"microMsg"、"WeiXin" |
| 连拍 | "_HDR"、"_burst"、"连拍"、"連拍"、"버스트" |
| 视频 | 视频文件扩展名 |

## 存储与性能

| 格式 | 适用场景 | 速度 | 上下文影响 |
|------|----------|------|------------|
| **SQLite** (.db) | 10 万+ 照片 | 查询快 400 倍 | 数据留在本地数据库，无上下文膨胀 |
| **CSV** (.csv) | 小型图库（<1 万） | 小集合适用 | CSV 内容可能膨胀 AI 上下文 |

### 性能基准（MacBook Pro M3 Pro）

| 照片数 | 扫描 | 精确去重 | 相似去重（全部） | 生成计划 | 总计 |
|--------|------|----------|-----------------|----------|------|
| 1K | 1.3s | 0.06s | 1.2s | 0.1s | ~3s |
| 10K | 12s | 0.07s | 49s | 0.3s | ~66s |
| 50K | 58s | 0.13s | ~8min | 0.5s | ~10min |

## 支持的格式

| 类型 | 扩展名 |
|------|--------|
| 图像 | jpg, jpeg, png, bmp, gif, tif, tiff, heic, heif, webp |
| RAW | dng, cr2, nef, arw |
| 视频 | mov, mp4, m4v, avi, mkv, 3gp, mpg, mpeg, hevc, wmv, flv |

## 脚本参考

| 脚本 | 用途 | 输入 | 输出 |
|------|------|------|------|
| `quick_scan.py` | 零安装快速扫描（仅标准库，SHA-256 + Apple QL） | 照片目录或 `.photoslibrary` | `.db` |
| `scan_photos.py` | 遍历目录提取元数据 + GPS + 相机 + **地名** | 照片视频目录 | `.db` 或 `.csv` |
| `scan_photos_library.py` | 扫描 Photos.app 图库（读取 Photos.sqlite） | `.photoslibrary` 包 | `.db` 或 `.csv` |
| `find_exact_duplicates.py` | 按 SHA-256 分组精确重复 | `.db` 或 `.csv` 索引 | `duplicates_exact.csv` |
| `find_similar_photos.py` | 按 pHash、Apple QL、缩放、跨格式、连拍分组相似图像 | `.db` 或 `.csv` 索引 | `duplicates_similar.csv` |
| `generate_move_plan.py` | 智能评分生成移动计划 | 重复 CSV + 索引 | `move_plan.csv` |
| `apply_move_plan.py` | 执行移动计划 + 撤销支持 | `move_plan.csv` | `move_log.csv` |
| `organize_photos.py` | 一键交互式流程（按日期/分类/**按地点**） | 来源目录 | 完整流程输出 |
| `import_to_photos.py` | 导入 Photos.app 并去重 | 来源目录 | 导入报告 JSON |
| `generate_preview.py` | HTML 缩略图预览 | 重复 CSV + 索引 | `preview.html` |
| `generate_review.py` | 交互式审核页面（智能策略规则） | `.db` 索引 + 重复 CSV | `review.html` + 决策 CSV |
| `detect_privacy_risks.py` | 查找敏感文档（身份证/银行卡/护照/密码） | `.db` 索引 | `.json` / `.csv` / `.txt` 报告 |
| `assess_quality.py` | 模糊/亮度/对比度/质量评分(0-100) | `.db` 索引 | DB 列 + `.csv` / `.json` 报告 |
| `detect_live_photos.py` | 识别 Live Photo 配对(HEIC+MOV) | `.db` 索引 | `live_photo_group` 列 |
| `find_orphan_raw.py` | 查找无 JPEG 伴侣的 RAW 文件 | `.db` 索引 | `.csv` / `.json` 报告 |
| `generate_timeline.py` | 交互式 HTML 时间线（年/月/日缩放） | `.db` 索引 | `timeline.html` |
| `compare_libraries.py` | Photos.app vs 文件系统对比(SHA-256) | `.db` + `.photoslibrary` | `.json` / `.csv` 报告 |
| `import_google_takeout.py` | 导入 Google Photos 导出+合并元数据 | Takeout 目录 | `.db` 索引 |
| `gpx_geotag.py` | 从 GPX 轨迹文件补 GPS | `.db` 索引 + `.gpx` | DB 列 + EXIF |
| `cluster_events.py` | 按时间+地点自动分组为事件 | `.db` 索引 | `.json` / `.csv` 报告 |
| `find_similar_videos.py` | 视频去重(帧采样+pHash) | `.db` 索引 | `.csv` 报告 |
| `rename_photos.py` | 按 EXIF 日期/相机/地点智能重命名 | `.db` 索引 | 重命名文件 + 撤销记录 |
| `generate_album_report.py` | HTML 相册整理报告（前后对比） | `.db` 索引 + 统计 | `album_report.html` |
| `library_stats.py` | 照片库健康与洞察（只读，**地点分布**） | `.db` 索引 | 终端 / JSON / `health.html` |
| `reverse_geocode.py` | GPS → 地名（城市/地区/国家） | 经纬度坐标 | 地名文本 |
| `edit_exif.py` | EXIF 编辑：移除 GPS、设置日期、写入标签 | 索引数据库或文件路径 | 修改后的文件 + 日志 |
| `photo_metadata.py` · `constants.py` · `applescript_utils.py` | 公共内部模块（哈希/EXIF、常量、AppleScript） | — | — |

## 依赖

### 核心（零安装）

| 内容 | 方式 |
|------|------|
| Python 3.9+ | 内置标准库：`hashlib`、`sqlite3`、`os`、`argparse`、`json`、`math` |
| Apple QL 检测 | 读取 `ZCOMPUTEDASSETATTRIBUTES` 预计算向量 — 无需额外依赖 |
| SHA-256 去重 | 使用标准库 `hashlib.sha256` |

### 可选（安装后增强功能）

| 包 | 用途 | 缺少时的回退 |
|----|------|-------------|
| **Pillow** | 图像尺寸、格式检测 | 使用 Photos.app 元数据中的尺寸 |
| **piexif** | EXIF 日期、GPS、相机信息 | 使用文件修改时间/Photos.app 日期 |
| **imagehash** | 感知哈希（pHash）相似度 | Apple QL 检测（零依赖替代方案） |
| **pillow-heif** | HEIC/HEIF 完整支持 | HEIC 文件跳过 pHash |
| **photoscript** | 高级 Photos.app 导入 | osascript 回退（无额外依赖） |
| **pyobjc-framework-Photos** | 底层 Photos.app 控制 | osascript 回退 |

**所有可选依赖均优雅降级** — SnapTidy 打印警告并以缩减功能继续运行，不会崩溃，无硬性要求。

## 平台兼容性

| 平台 | 配置文件 | 安装路径 |
|------|----------|----------|
| Claude Code | `CLAUDE.md` | `~/.claude/skills/snaptidy/` |
| Cursor | `.cursor/rules/snaptidy.mdc` | 项目 `.cursor/rules/` |
| Windsurf | `.windsurf/rules/snaptidy.md` | 项目 `.windsurf/rules/` |
| WorkBuddy | `SKILL.md` | `~/.workbuddy/skills/snaptidy/` |
| OpenClaw | `SKILL.md` + `clawhub.yaml` | `~/.openclaw/skills/snaptidy/` |
| 任意 AI 代理 | `AGENTS.md` | 项目根目录 |

## 参与贡献

欢迎贡献！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

特别欢迎以下方向：

- **按日期重新组织** — 基于 EXIF 日期按年/月文件夹整理
- **视频去重** — 使用 ffmpeg/opencv 进行关键帧哈希
- **跨平台支持** — 扩展到 Linux 和 Windows
- **离线地理编码回退** — 打包轻量级离线逆地理编码数据库

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。

## Star History

<a href="https://star-history.com/#chicogong/snaptidy&Date">
  <img src="https://star-history.com/#chicogong/snaptidy&Date" alt="Star History Chart" width="600">
</a>

## 许可证

本项目使用 MIT 许可证 — 详见 [LICENSE](LICENSE) 文件。

## 致谢

受 macOS 自动化社区和 [organize](https://github.com/tfeldmann/organize)、[FileLens](https://github.com/priyanshul/get-file-details)、[Anthropic Skills](https://github.com/anthropics/skills)、[Apple CLI](https://github.com/Sankalpcreat/Apple-CLI) 等工具启发。
