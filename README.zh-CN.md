# SnapTidy

[English](README.md) | 简体中文

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/Platform-macOS-black.svg?style=flat-square)](https://www.apple.com/macos)
[![AI Skill](https://img.shields.io/badge/AI-Skill-purple.svg?style=flat-square)](https://github.com/topics/ai-skill)
[![Version](https://img.shields.io/badge/Version-3.3-green.svg?style=flat-square)](https://github.com/chicogong/snaptidy)

> macOS 照片视频整理去重工具。通过 AI 对话，安全地整理、去重和重构你的照片库。

## 目录

- [为什么选择 SnapTidy？](#为什么选择-snaptidy)
- [新功能](#v33-新功能)
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

核心区别？**安全第一，零风险。** SnapTidy 永不删除任何东西。它以只读方式扫描，生成人类可读的计划，仅在明确批准后移动文件 — 可选移至 macOS 废纸篓（通过 Finder 恢复）。

## v3.3 新功能

| 功能 | 说明 |
|------|------|
| 📱 **导入 Photos.app** | 从外置硬盘/安卓导入并自动去重 |
| 👥 **共享相册读取** | 从 Photos.sqlite 读取共享相册信息 |
| ☁️ **iCloud 同步感知** | 检测仅存 iCloud 的文件和下载状态 |
| 🔄 **断点续传** | 导入流程支持中断后续传 |
| 💾 **零数据丢失** | 流式 SQLite 写入 — 逐条即时提交 |

<details>
<summary>历史版本</summary>

| 版本 | 功能 |
|------|------|
| 🗄️ **v2.0** | SQLite 存储（比 CSV 快 400 倍）、智能优先级规则、macOS 废纸篓模式、GPS/相机元数据、自动分类 |
| 🔍 **v3.0** | 缩放去重、跨格式去重（HEIC↔JPEG）、连拍检测、Photos.app 扫描、PyObjC 删除 |
| 🖥️ **v3.1** | 交互式流程、HTML 缩略图预览（保留/移动标记）、撤销系统、iCloud/安卓/外置硬盘检测、15+ 语言 |
| 📅 **v3.2** | 按日期（YYYY/MM）和按分类整理模式 |

</details>

## 核心特性

- 🎯 **SHA-256 精确去重** — 在整个图库中查找字节完全相同的重复文件
- 👁️ **感知哈希相似度** — 使用 pHash 检测视觉相同的图像，支持模糊汉明距离阈值
- 🔀 **跨格式去重** — 同一照片的 HEIC 和 JPEG 版本
- 📐 **缩放去重** — 同一照片不同分辨率
- 📸 **连拍检测** — 通过 SubSecTime 分组连拍照片
- 📋 **丰富元数据索引** — 提取文件大小、EXIF 日期、GPS、相机信息等写入 SQLite 或 CSV
- 🛡️ **安全优先设计** — 只读扫描、仅移动操作、废纸篓模式、CSV 审计跟踪
- 💾 **零数据丢失** — 流式 SQLite 写入，逐条提交
- 💬 **对话驱动** — 通过 AI 助手交互，无需 GUI 或配置文件
- ⚡ **零配置** — 指向目录即可开始
- 🔌 **多平台** — 兼容 Claude Code、Cursor、Windsurf、WorkBuddy 等
- 🗄️ **可扩展** — SQLite 后端处理 10 万+ 照片

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

```
┌─────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  扫描   │────>│  查找重复    │────>│  生成计划    │────>│  审核并执行   │
│         │     │              │     │             │     │              │
│ 照片    │     │ SHA-256 +    │     │ 智能移动    │     │ 你确认后      │
│ 和视频  │     │ pHash ±阈值  │     │ 计划 (CSV)  │     │ 再执行移动    │
└─────────┘     └──────────────┘     └─────────────┘     └──────────────┘
  只读              只读                只读               仅移动/废纸篓
```

1. **扫描** — 遍历照片/视频目录，提取元数据（大小、SHA-256、EXIF 日期、GPS、相机信息、尺寸、感知哈希、自动分类、文件夹标签），写入 SQLite（推荐）或 CSV
2. **查找重复** — 按精确哈希（SHA-256）和感知哈希（pHash）分组，支持模糊阈值
3. **生成计划** — 智能多因素评分决定保留哪张，支持可配置策略和文件夹偏好
4. **审核并执行** — 打开 CSV 计划验证，确认后执行，可选移至文件夹或废纸篓

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
# 第 1 步：扫描（大型图库推荐 SQLite）
python3 scripts/scan_photos.py --input /path/to/your/photos --output ./photo_index.db

# 第 2 步：查找精确重复
python3 scripts/find_exact_duplicates.py --index ./photo_index.db --output ./duplicates_exact.csv

# 第 3 步（可选）：查找感知相似图像
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./duplicates_similar.csv
python3 scripts/find_similar_photos.py --index ./photo_index.db --output ./similar.csv --detect-all

# 第 4 步：生成智能移动计划
python3 scripts/generate_move_plan.py \
    --duplicates ./duplicates_exact.csv \
    --index ./photo_index.db \
    --plan ./move_plan.csv \
    --target-root /path/to/your/photos \
    --prefer-folder "DCIM" --strategy quality

# 第 5 步：HTML 缩略图预览（可选但推荐）
python3 scripts/generate_preview.py \
    --duplicates ./duplicates_similar.csv \
    --index ./photo_index.db \
    --output ./preview.html

# 第 6 步：审核移动计划后执行
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --mode trash

# 第 7 步：如需撤销
python3 scripts/apply_move_plan.py --plan ./move_plan.csv --undo
```

### 导入 Photos.app

```bash
# 干运行：预览导入内容
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --dry-run

# 导入所有唯一照片（自动跳过重复）
python3 scripts/import_to_photos.py --source /Volumes/External/Photos --album "Vacation 2025"

# 从安卓 DCIM 导入
python3 scripts/import_to_photos.py --source /Volumes/Android/DCIM --album "Android Import"
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

# 检测已连接的安卓设备和外置硬盘
python3 scripts/organize_photos.py --source /any --detect-sources
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
| `scan_photos.py` | 遍历目录提取元数据 + GPS + 相机 | 照片视频目录 | `.db` 或 `.csv` |
| `scan_photos_library.py` | 扫描 Photos.app 图库（读取 Photos.sqlite） | `.photoslibrary` 包 | `.db` 或 `.csv` |
| `find_exact_duplicates.py` | 按 SHA-256 分组精确重复 | `.db` 或 `.csv` 索引 | `duplicates_exact.csv` |
| `find_similar_photos.py` | 按 pHash 分组相似图像 | `.db` 或 `.csv` 索引 | `duplicates_similar.csv` |
| `generate_move_plan.py` | 智能评分生成移动计划 | 重复 CSV + 索引 | `move_plan.csv` |
| `apply_move_plan.py` | 执行移动计划 + 撤销支持 | `move_plan.csv` | `move_log.csv` |
| `organize_photos.py` | 一键交互式流程 | 来源目录 | 完整流程输出 |
| `import_to_photos.py` | 导入 Photos.app 并去重 | 来源目录 | 导入报告 JSON |
| `generate_preview.py` | HTML 缩略图预览 | 重复 CSV + 索引 | `preview.html` |

## 依赖

| 包 | 用途 |
|----|------|
| **Pillow** | 图像读取、尺寸、格式转换 |
| **piexif** | EXIF 数据提取（日期、GPS、相机信息） |
| **imagehash** | 感知哈希计算 |

仅 3 个核心依赖，无重型框架，SQLite 内置于 Python。

可选：**pillow-heif**（HEIC/HEIF 支持）、**pyobjc-framework-Photos**（Photos.app 删除）、**photoscript**（Photos.app 导入）

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
- **按地点整理** — GPS 元数据反向地理编码

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

本项目使用 MIT 许可证 — 详见 [LICENSE](LICENSE) 文件。

## 致谢

受 macOS 自动化社区和 [organize](https://github.com/tfeldmann/organize)、[FileLens](https://github.com/priyanshul/get-file-details)、[Anthropic Skills](https://github.com/anthropics/skills)、[Apple CLI](https://github.com/Sankalpcreat/Apple-CLI) 等工具启发。
