# SPEC — Tool tải truyện → dịch → txt → mp3

> Tài liệu này mô tả **toàn bộ yêu cầu & chuẩn** để tạo/mở rộng các tool tải
> truyện trong repo `alicesw`. Viết cho **AI đọc là tự hiểu và tự thêm được site
> mới** mà không cần hỏi lại. Đã áp dụng cho 3 site: `sosing.com`, `langyou`,
> `18av.mm-cg`.

---

## 1. Mục tiêu & pipeline tổng thể

Từ một **site truyện tiếng Trung** → ra **file mp3 tiếng Việt** cho AI/người tự đọc:

```
[Site TQ]
  │  crawl theo TỪ KHOÁ tìm kiếm (--wd), phân trang
  ▼
[Danh sách truyện]  (url, tiêu đề Hán, thể loại)
  │  tải nội dung từng truyện, parse text
  ▼
[Nội dung Hán]
  │  CHỐNG TRÙNG qua registry chung (bắt buộc — mục 3)
  ├── TRÙNG  → ghi file "_<tên>.txt" (không dịch lại) + thêm link vào bản ghi cũ
  └── MỚI    → dịch Trung→Việt + đổi tên riêng Hán-Việt
  ▼
[txt tiếng Việt]  → <tooldir>/txt/*.txt   (có header: tiêu đề, nguồn, thể loại)
  │  txt_to_mp3.py (gTTS, watcher)
  ▼
[mp3 tiếng Việt]  → .../mp3/*.mp3
  │  compress_mp3.py (ffmpeg, 32kbps)
  ▼
[mp3 nén nhỏ]
```

Mỗi tool site là **workspace tự chứa** trong thư mục riêng (vd `18av.mm-cg/`,
`langyou4.langyou895/`, `sosing.com/`), chỉ **tái dùng logic** từ repo cha.

---

## 2. Tái dùng stack (KHÔNG viết lại)

Mọi downloader site mới **import lại** thay vì tự code phần dịch/registry:

```python
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "sosing.com"))
sys.path.insert(0, str(_ROOT))
import sosing_downloader as sd     # registry dedup + dịch + ghi file
dl = sd.dl                          # cấu hình engine dịch
```

Hàm dùng từ `sosing_downloader` (as `sd`):

| Hàm | Việc |
|-----|------|
| `sd.registry_check_and_update(cn_title, chapters_cn, url, vi_title, translated_path=...)` | Chống trùng + cập nhật registry. Trả `(is_dup, entry_id, entry)`. |
| `sd.write_dup_txt(txt_dir, vi_title, cn_title, url, entry_id, entry)` | Ghi file `_`-prefix cho truyện TRÙNG (không dịch). |
| `sd.write_story(txt_dir, vi_title, cn_title, url, tags_vi, total, chapters)` | Ghi file txt hoàn chỉnh (có header). |
| `sd.translate_block(text)` | Dịch 1 khối Trung→Việt (tự chunk). |
| `sd.translate_title_vi(cn_title)` / `sd.translate_tags_vi(tags)` | Dịch tiêu đề / thể loại. |
| `sd.safe_filename(name)` | Tên file an toàn Windows. |

`sd` lại tái dùng `alicesw_downloader` (engine Caiyun→Google, render tên riêng
Hán-Việt) + `hanviet.hanzi_to_hanviet` (fallback chữ Hán sót).

Engine dịch chọn bằng `dl.ENGINE ∈ {free, caiyun, google, gemini}`
(`free` = Caiyun→Google). `gemini` cần `dl.GEMINI_API_KEY`.

---

## 3. CHUẨN CHỐNG TRÙNG (BẮT BUỘC cho mọi tool)

**Lý do:** các site (sosing/langyou/fsnovel/18av) chia sẻ cùng kho truyện Trung →
tải chồng chéo rất nhiều (đo được ~86% ở sosing). Phải dedup qua **registry chung**.

- Registry: `downloaded/downloaded_registry.json` (~5700+ bản ghi, key = novel id chuỗi).
- Nhận diện trùng bằng **vân tay nội dung** (`dau_van_tay_noi_dung.doan_mau_chu_han`
  = 200 ký tự Hán đầu chương 1) **VÀ** tiêu đề Hán.
- **Chuẩn hoá 简↔繁 về giản thể** (opencc `t2s`) trước khi so — vì registry có cả
  phồn thể (fsnovel/sosing/18av) lẫn giản thể (langyou). Đây là điểm mấu chốt để
  một site phồn thể vẫn khớp bản ghi giản thể.
- **MỚI** → thêm bản ghi (id = max+1) + vân tay, dịch + lưu txt, ghi
  `file_cuc_bo.translated`.
- **TRÙNG** → thêm link nguồn vào `links` của bản ghi cũ; file txt đặt tên có **`_`
  ở đầu**, nội dung nhúng thông tin bản ghi trùng (KHÔNG dịch lại → tiết kiệm).
- Ghi registry **nguyên tử** (temp+replace) + khoá `RLock` + lockfile liên-tiến-trình
  (`_RegFileLock`, O_EXCL) → chạy nhiều tiến trình/`--workers` cùng ghi vẫn an toàn,
  không mất cập nhật / trùng ID. (Đã có sẵn trong `sd.registry_check_and_update`.)

Deps: `opencc-python-reimplemented`.

---

## 4. Cấu trúc chuẩn của MỘT downloader site

Mỗi site có 2 file (đặt trong thư mục site, tên module hợp lệ — không bắt đầu bằng số):

### `<site>_downloader.py`
- Args chuẩn: `--wd` (từ khoá, mặc định `母子`), `--pages`, `--limit`,
  `--engine`, `--gemini-key`, `--workers`, `--no-translate`, `--no-resume`.
- `fetch(url)` — `urllib` + retry + gzip (nếu site không có Cloudflare).
- `search_url(wd, page)` — build URL tìm kiếm phân trang.
- `collect_stories(html)` — trả `[(url, cn_title, category), ...]` từ trang tìm kiếm
  (giữ thứ tự, bỏ trùng, tách `[thể loại]` nếu có).
- `parse_story(html)` — trích nội dung Hán từ container của site.
- `process_story(...)` — gọi registry dedup → dịch/ghi (mục 3).
- `crawl(...)` — lặp trang tìm kiếm tới khi hết truyện mới hoặc đạt `--pages/--limit`;
  chạy song song `--workers` qua `ThreadPoolExecutor`.
- Resume: URL đã xong lưu `txt/_done.json`.
- `--no-translate` → chỉ ghi bản gốc JSON vào `txt/origin/*.json`
  (`{url, cn_title, tags, total_pages, chapters_cn}`).

### `<site>_translate.py` (luồng dịch riêng — watcher)
- Đọc `txt/origin/*.json` → dịch + dedup registry → ghi `txt/*.txt`.
- Resume qua `txt/_translated.json`. Có `--once` (quét 1 lần) hoặc chạy liên tục.
- Cho phép **2 cửa sổ song song**: 1 tải nhanh (`--no-translate`), 1 dịch liên tục.

### Cách chạy (mẫu, thay `<site>`)
```
# Một cửa sổ (tải + dịch):
py -u <site>_downloader.py --wd 母子 --engine google --workers 5

# Hai cửa sổ (khuyên dùng khi dịch chậm):
py -u <site>_downloader.py --wd 母子 --no-translate          # cửa sổ 1
py -u <site>_translate.py  --engine google --workers 5       # cửa sổ 2
```

---

## 5. txt → mp3 → nén (giai đoạn TTS)

Dùng chung, KHÔNG viết lại theo site:

```
# txt tiếng Việt -> mp3 (gTTS, watcher, resume từng chunk, xoay ProtonVPN chống 429)
py -u txt_to_mp3.py --dir <site>/txt
py -u txt_to_mp3.py --dir <site>/txt --once --max-size 1.5

# nén mp3 xuống 32kbps tại chỗ (cần ffmpeg)
py compress_mp3.py --dir <site>/txt/mp3 --recursive
```

- `txt_to_mp3.py`: quét thư mục, file `.txt` mới/đã sửa → tạo `.mp3` (tiếng Việt)
  vào thư mục con `mp3/`; nhớ trạng thái `_tts_progress.json`; gọi đơn luồng +
  backoff chống lỗi 429 của Google; ghép chunk bằng nối byte mp3 (+ ffmpeg hậu kỳ nếu có).
- `compress_mp3.py`: nén 32kbps (mặc định), bỏ qua file vừa sửa <10s, có `--dry-run`.

---

## 6. CHECKLIST thêm SITE MỚI (recipe)

1. **Khảo sát site** (bằng `urllib` + BeautifulSoup, lưu HTML mẫu ra scratchpad):
   - Có Cloudflare/Turnstile không? Không → `urllib` thuần (nhanh). Có → cần
     SeleniumBase CDP mode (xem cách sosing bypass Turnstile).
   - Chữ **giản thể hay phồn thể**? (opencc lo phần khớp registry.)
   - URL tìm kiếm phân trang = gì? Bao nhiêu kết quả/trang, tổng trang?
   - URL trang truyện = gì? 1 trang = cả truyện hay có phân chương/phân trang?
   - Nội dung nằm trong selector nào? Tiêu đề có tiền tố `[thể loại]` không?
2. **Copy** `langyou4.langyou895/langyou_downloader.py` + `langyou_translate.py`
   làm khuôn (site không Cloudflare) → sửa: `BASE`, `search_url`, `story_url`,
   regex link, `collect_stories`, `parse_story`.
3. **Giữ nguyên** phần registry/dịch/ghi (gọi `sd.*`) và bộ args chuẩn.
4. **Test end-to-end**: chạy `--no-translate --limit 3`, kiểm tra JSON có đủ nội
   dung (đếm ký tự > 0!); rồi `<site>_translate.py --once` kiểm tra có ra txt,
   có phát hiện TRÙNG (log `TRUNG (registry ID ...)`).
5. **Lưu memory** (`memory/<site>-downloader-tool.md`) + cập nhật `MEMORY.md`.

### Gotchas HTML đã gặp (nhớ để không sập bẫy)
- **`<br>` không phá được bằng `br.replace_with("\n")`** với `html.parser`
  (mất text). Dùng `container.get_text("\n")` (separator) để ngắt dòng.
- Container 18av: `span.content_18h_wpcg` bọc cả **khung điều khiển cỡ chữ** →
  lọc bỏ dòng chứa `文字放大|縮小|原始|放大|自訂|行距|文字大小`.
- Trang tìm kiếm có thể lẫn link "truyện gợi ý" ở sidebar → chỉ lấy link trong
  vùng kết quả, hoặc dùng regex link chặt + kiểm số lượng khớp mong đợi/trang.
- Tiêu đề thường có hậu tố ngày (langyou: `MM-DD`) hoặc tiền tố `[thể loại]`
  (18av) → strip trước khi làm `cn_title`.

---

## 7. Bảng đặc thù từng site (đã làm)

| Site | Cloudflare | Chữ | Tìm kiếm | Trang truyện | Nội dung |
|------|-----------|-----|----------|--------------|----------|
| **sosing.com** | Có (Turnstile → SeleniumBase CDP) | Phồn/Giản | tag id | phân chương | (xem memory) |
| **langyou** | Không | Giản thể | `/artsearch/<wd>------<page>-.html` | `/artdetail-<id>.html`, 1 trang | `div.artcontent` `<p>` |
| **18av.mm-cg** | Không | Phồn thể | `/zh/novel_search/all/<wd>/<page>.html` (24/trang) | `/zh/novel_content/<id>/content.html`, 1 trang | `span.content_18h_wpcg` (get_text `\n`) |

---

## 8. Deps

`beautifulsoup4`, `translators`, `opencc-python-reimplemented`, `gTTS`,
`ffmpeg` (PATH, cho mp3/nén), `seleniumbase`+Chrome (chỉ site có Cloudflare).
```
py -m pip install beautifulsoup4 translators opencc-python-reimplemented gTTS
```
