# SnapTidy Promotion Guide

Complete playbook for promoting SnapTidy across awesome-lists, social platforms, and developer communities.

---

## Awesome-List Submissions

Awesome-lists are curated GitHub lists that drive organic discovery. Submit PRs to each repo below.

### Priority Targets

| Repository | Stars | Relevance | PR Status |
|-----------|-------|-----------|-----------|
| [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | 63K+ | Perfect — AI skill for photo management | ⬜ Pending |
| [phmullins/awesome-macos-commandline](https://github.com/phmullins/awesome-macos-commandline) | 4K+ | High — macOS CLI photo tool | ⬜ Pending |
| [jsnyder/awesome-llm-cli-apps](https://github.com/jsnyder/awesome-llm-cli-apps) | 1K+ | High — LLM-powered CLI app | ⬜ Pending |
| [sindresorhus/awesome](https://github.com/sindresorhus/awesome) | 300K+ | Submit to `awesome-cli` or `awesome-python` sublist | ⬜ Pending |
| [vinta/awesome-python](https://github.com/vinta/awesome-python) | 220K+ | Submit under `Image Processing` or `CLI Tools` | ⬜ Pending |

### PR Template

```markdown
## Add SnapTidy — AI-Powered Photo Deduplication & Organizer for macOS

### What is SnapTidy?

SnapTidy is an open-source AI-powered photo and video organizer for macOS. It finds duplicate photos using SHA-256 exact matching, perceptual hashing (pHash), and Apple's built-in ML feature vectors. Unlike traditional photo management apps, SnapTidy is conversation-driven — you describe what you want in natural language, and it handles scanning, dedup, and organization safely.

### Why it belongs on this list

- **[Relevant category match]**: SnapTidy is a [CLI tool / AI skill / macOS utility] that [specific relevance to this list]
- **Active development**: 30+ scripts, v3.13.1, regular releases
- **Zero-install core**: Core features (SHA-256, Apple QL, metadata) work with just Python stdlib
- **Safety-first**: Read-only scanning, human-approved actions, macOS Trash recovery
- **MIT licensed**: Fully open source

### Links

- Repository: https://github.com/chicogong/snaptidy
- Documentation: https://github.com/chicogong/snaptidy#readme
- License: MIT

### Checklist

- [x] The item was added to the correct alphabetical position
- [x] The item description follows the format: `- [SnapTidy](https://github.com/chicogong/snaptidy) - Description`
- [x] The item has been verified to meet the list's contribution guidelines
- [x] The PR title follows the convention: `Add SnapTidy`
```

### Submission Tips

1. **Read CONTRIBUTING.md** of each awesome-list before submitting
2. **Match alphabetical order** — most lists require it
3. **Keep description concise** — one line, under 100 chars
4. **One PR per repo** — don't batch multiple items
5. **Respond to feedback** promptly if maintainers request changes

---

## Hacker News (Show HN)

Best time: **Tuesday–Thursday, 7–10 AM Pacific Time** (when US East Coast is at work, Europe is active).

### Title

```
Show HN: SnapTidy – AI-powered photo dedup tool that finds duplicates via pHash, ML vectors, SHA-256
```

### Body Template

```
Hi HN,

I built SnapTidy, an open-source photo deduplication and organization tool for macOS.

The problem: After years of iPhone shots, iCloud exports, Android transfers, WeChat saves, screenshots, and old backups, my photo library had thousands of duplicates — exact copies, same photo at different resolutions, HEIC + JPEG pairs, and burst shots. Existing tools were either expensive GUI apps or didn't handle cross-format dedup.

SnapTidy takes a different approach:
1. **Multiple dedup strategies**: SHA-256 exact match, perceptual hash (pHash) for visual similarity, Apple's built-in ML feature vectors (zero-dependency), cross-format detection (HEIC↔JPEG), scaled duplicate detection, burst photo grouping
2. **Safety-first**: Everything is read-only by default. It produces a human-readable CSV plan, and only moves files after you explicitly approve. Supports macOS Trash (recoverable via Finder).
3. **Conversation-driven**: Works as an AI assistant skill — you describe what you want in natural language
4. **30+ scripts**: Quality assessment, privacy risk detection, GPS reverse geocoding, timeline viewer, Google Takeout import, video dedup, EXIF editing, corrupted file detection, and more
5. **Zero-install core**: SHA-256 dedup and Apple ML vector detection work with just Python stdlib — no pip install needed

Benchmarked on 50K photos (~10 min full pipeline on M3 Pro).

GitHub: https://github.com/chicogong/snaptidy

I'd love feedback on the dedup strategies and any features you'd want to see. Thanks!
```

### HN Guidelines

- Title ≤ 80 chars (HN truncates longer titles)
- First comment should be from the submitter explaining the project
- Be available to respond to comments for 2–3 hours after posting
- Don't ask friends to upvote (HN detects and penalizes this)
- Engage genuinely with critical feedback

---

## Reddit

### Target Subreddits

| Subreddit | Members | Best Post Type | Rules Check |
|-----------|---------|---------------|-------------|
| r/macapps | 200K+ | Text post with link in body | No link posts, must be self-post |
| r/opensource | 300K+ | Link post | Must be open source |
| r/selfhosted | 400K+ | Text post | Focus on self-hostable aspect |
| r/photography | 4M+ | Text post, photography angle | No direct promo, add value |
| r/Python | 800K+ | Link post | Follow `self-promotion` ratio |

### r/macapps Post Template

```
**SnapTidy — Free open-source photo dedup & organizer for macOS (pHash + Apple ML + SHA-256)**

I've been dealing with a bloated photo library for years — duplicates from iCloud exports, old Android transfers, WeChat saves, screenshots piling up. Commercial apps wanted $30–50 and didn't handle cross-format duplicates (HEIC + JPEG pairs).

So I built SnapTidy:

- **Multiple dedup strategies**: SHA-256 exact, perceptual hash (pHash), Apple ML feature vectors (zero-dependency!), cross-format (HEIC↔JPEG), scaled duplicates, burst detection
- **Safety-first**: Read-only scan → human-readable plan → you approve → move to Trash (recoverable via Finder)
- **30+ scripts**: Quality scoring, privacy risk detection (find ID cards/passports in your library), GPS reverse geocoding, timeline viewer, video dedup, Google Takeout import, EXIF editing, corrupted file detection
- **Zero-install core**: Works with just Python 3.9+ stdlib, no pip install required for basic features
- **Works as AI skill**: Describe what you want in natural language — no GUI, no config files

Runs on macOS 13+. Handles 50K+ photos (benchmarked ~10min full pipeline on M3 Pro).

GitHub: https://github.com/chicogong/snaptidy

Free and open source (MIT license). Would love feedback!
```

### Reddit Guidelines

- Read each subreddit's rules before posting
- **r/macapps**: Must be self-post (text), not link post
- **r/opensource**: Must clearly state license in title or body
- **r/selfhosted**: Emphasize offline/local processing, no cloud dependency
- **r/Python**: Maintain 10:1 comment-to-post ratio for self-promotion
- **r/photography**: Frame as solving a photographer's problem, not as a product launch
- Don't cross-post to more than 2 subreddits on the same day
- Engage with every comment

---

## dev.to Tutorial

Write a tutorial-style article — these get more organic traffic than promotional posts.

### Title

```
How I Built an AI-Powered Photo Dedup Tool That Handles HEIC, Burst Shots, and iCloud Placeholders
```

### Outline

1. **The Problem**: Photo libraries grow messy — duplicates from multiple devices, format conversions, iCloud exports
2. **Existing Solutions & Gaps**: Commercial apps ($$$), basic CLI tools (no cross-format), AI chatbots (can't access files)
3. **Architecture Decisions**:
   - Why perceptual hash (pHash) for visual similarity
   - How Apple's ML feature vectors work (zero-dependency advantage)
   - SQLite as the indexing backend (scales to 100K+ photos)
   - Safety-first design pattern (read-only → plan → approve → execute)
4. **Key Technical Challenges**:
   - Cross-format dedup (HEIC + JPEG of the same photo)
   - iCloud placeholder detection (thumbnails produce unreliable hashes)
   - Scaled duplicate detection (same photo at different resolutions)
   - Burst photo grouping via SubSecTime EXIF tag
5. **Results**: 50K photo library cleaned in ~10 minutes, found 3,000+ duplicates saving 12GB
6. **Open Source**: Link to GitHub, invite contributions

### dev.to Tags

`#python #opensource #showdev #productivity #macos #ai`

---

## V2EX

### Node

`/t/create` → 分享创造 (Share Creation)

### Title

```
SnapTidy — macOS 照片去重整理工具（pHash + Apple ML + SHA-256，开源免费）
```

### Body

```
各位 V2EX 的朋友好，

我开发了一个 macOS 照片去重和整理工具 SnapTidy，开源免费（MIT 协议）。

**解决的问题**：多年积累的照片库里有大量重复 —— iCloud 导出、安卓转移、微信保存、截图堆积。商业软件要 $30-50 且不支持跨格式去重（HEIC + JPEG 同一张照片）。

**核心功能**：
- 多种去重策略：SHA-256 精确去重、感知哈希 pHash 视觉相似、Apple ML 特征向量（零依赖）、跨格式去重（HEIC↔JPEG）、缩放去重、连拍检测
- 安全第一：只读扫描 → 生成可读计划 → 人工确认 → 移到废纸篓（可恢复）
- 30+ 脚本：质量评估、隐私检测（找出身份证/银行卡/护照）、GPS 逆地理编码、时间线视图、视频去重、Google Takeout 导入、EXIF 编辑、损坏文件检测
- 零安装核心：SHA-256 和 Apple ML 向量检测只需 Python 标准库
- AI 对话驱动：用自然语言描述需求，无需 GUI 或配置文件

**性能**：50K 张照片全流程约 10 分钟（M3 Pro）

GitHub: https://github.com/chicogong/snaptidy

欢迎反馈和建议！
```

---

## Product Hunt

### Launch Checklist

- [ ] Create a maker account (if not existing)
- [ ] Prepare product gallery (5 images minimum):
  1. Hero image with tagline (1270×760)
  2. Feature showcase (pipeline diagram)
  3. Before/after dedup screenshot
  4. Feature comparison table
  5. Terminal output example
- [ ] Write tagline (60 char max): `AI-powered photo dedup & organizer for macOS`
- [ ] Write description (260 char max): `Find duplicate photos with pHash, Apple ML vectors, and SHA-256. Cross-format dedup, iCloud handling, EXIF editing, privacy detection — all free and open source.`
- [ ] Prepare launch day schedule (7 AM PT)
- [ ] Line up 5+ early supporters for initial upvotes
- [ ] Prepare maker comment for launch

### Maker Comment Template

```
Hey Product Hunt! 👋

I built SnapTidy because my photo library was a mess — thousands of duplicates from iCloud, Android, WeChat, and old backups. Commercial apps were expensive and couldn't handle cross-format duplicates (HEIC + JPEG of the same photo).

SnapTidy uses multiple dedup strategies: exact SHA-256, perceptual hashing, and Apple's built-in ML vectors — all free and open source.

Would love your feedback! 🙏
```

---

## X / Twitter

### Tweet Templates

**Launch tweet**:
```
After months of development, I'm excited to share SnapTidy — a free, open-source photo dedup & organizer for macOS.

🎯 SHA-256 + pHash + Apple ML vectors
🔀 Cross-format dedup (HEIC↔JPEG)
🛡️ Safety-first: read-only scan, human-approved actions
⚡ Zero-install core

GitHub: https://github.com/chicogong/snaptidy

#opensource #macOS #photography #Python
```

**Feature highlight tweet** (post one per day):
```
Did you know SnapTidy can detect duplicates across different formats?

HEIC from your iPhone + JPEG export from WeChat = same photo, different format.

SnapTidy groups them and lets you keep the best quality version.

https://github.com/chicogong/snaptidy

#photodedup #macOS
```

---

## Launch Timeline (48-Hour Window)

### Week Before Launch (Prep)

- [ ] Finalize all code, tests, and documentation
- [ ] Ensure README is polished with screenshots/GIFs
- [ ] GitHub Pages landing page live
- [ ] Star History chart embedded in README
- [ ] Prepare all post templates (this file)
- [ ] Submit PRs to awesome-lists (may take days to merge)
- [ ] Write dev.to article draft
- [ ] Create Product Hunt gallery images
- [ ] Notify 5-10 friends/supporters about launch day

### Day 1 — Launch Day (Tuesday or Wednesday)

| Time (PT) | Action |
|-----------|--------|
| 6:00 AM | Final check — repo, docs, landing page all live |
| 7:00 AM | Post to Hacker News (Show HN) |
| 7:15 AM | Post to r/macapps |
| 7:30 AM | Post to r/opensource |
| 8:00 AM | Post to V2EX (分享创造) |
| 8:30 AM | Post launch tweet on X/Twitter |
| 9:00 AM | Publish dev.to article |
| 9:00–12:00 | Monitor and respond to comments on all platforms |
| 12:00 PM | Post to r/selfhosted |
| 2:00 PM | Post feature highlight tweet |
| Evening | Engage with all comments, thank supporters |

### Day 2 — Sustain

| Time (PT) | Action |
|-----------|--------|
| Morning | Respond to overnight comments (HN, Reddit, dev.to) |
| 9:00 AM | Post to r/Python (if 10:1 ratio maintained) |
| 10:00 AM | Product Hunt launch (if ready) |
| Afternoon | Engage with Product Hunt comments |
| Evening | Post second feature highlight tweet |

### Day 3–7 — Compound

- [ ] Follow up on awesome-list PRs (respond to reviewer feedback)
- [ ] Post 1 feature highlight tweet per day
- [ ] Engage with any blog mentions or reviews
- [ ] Share user feedback/testimonials
- [ ] Submit to additional awesome-lists as PRs merge

### Week 2+ — Ongoing

- [ ] Write follow-up blog post (e.g., "What I learned launching SnapTidy")
- [ ] Submit to more niche awesome-lists
- [ ] Consider Product Hunt launch (if not done Day 2)
- [ ] Engage with GitHub issues and PRs from new users
- [ ] Share milestones (first 100 stars, first contributor, etc.)

---

## SEO Checklist

- [x] GitHub repo description optimized with keywords
- [x] 20 GitHub topics (max) covering: dedup, photo, macOS, EXIF, iCloud, backup, image-processing
- [x] GitHub Pages landing page with JSON-LD `SoftwareApplication` schema
- [x] Open Graph + Twitter Card meta tags
- [x] README H1/H2/H3 hierarchy with keywords in first 100 words
- [ ] README includes screenshots/GIFs (capture when available)
- [ ] Star History chart in README
- [ ] Canonical URL set on landing page
- [ ] Internal links between README and landing page
- [ ] Submit to Google Search Console (after Pages is live)

---

## Metrics to Track

| Metric | Target (30 days) | Target (90 days) |
|--------|-----------------|-----------------|
| GitHub Stars | 50 | 200 |
| GitHub Forks | 5 | 20 |
| GitHub Pages views | 500 | 2,000 |
| dev.to article views | 1,000 | 5,000 |
| HN upvotes | 50 | — |
| Reddit upvotes (total) | 100 | — |
| Awesome-list PRs merged | 2 | 5 |
| Contributors | 1 | 3 |

---

*Last updated: 2026-06-17*
