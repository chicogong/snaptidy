# Smart Priority Rules

When deciding which duplicate to KEEP, SnapTidy scores files by:

| Factor | Weight | Rationale |
|--------|--------|-----------|
| Resolution (pixels) | High | Higher res = better quality |
| File size | Medium | Larger = less compressed |
| EXIF completeness | High | Has metadata = likely original |
| Format (RAW > HEIC > JPG) | Medium | Better format = better quality |
| Category (photo > wechat > screenshot) | Medium | Real photos over screenshots |
| Folder priority (auto) | Medium | DCIM/Photos > Backup/Downloads |
| Folder preference (manual) | High | User-specified priority folders |
| Photos.app favorite | High | Never move favorited photos |

Strategies: `--strategy quality` (default), `oldest`, `newest`, `folder`

## Auto-Categorization (15+ Languages)

| Category | Detected by |
|----------|------------|
| photo | Default for camera photos (including `IMG_*.JPG`) |
| screenshot | English, Chinese, Japanese, Korean, Russian, French, German, Spanish, Italian, Portuguese, Dutch, Thai, Vietnamese, Indonesian, or iOS `IMG_\d+.PNG`, or Photos.app screenshot flag |
| wechat | "mmexport", "wx_camera_", "microMsg", "WeChat", "KakaoTalk", "LINE_" |
| burst | "_HDR", "_burst", burst translations, or HDR flag from Photos.app |
| video | Video file extensions |
