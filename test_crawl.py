import requests, json, re, sys, io, time
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; PJH110 Build/SP1A.210812.016) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36",
    "Referer": "https://www.alicesw.com/",
}
BASE = "https://www.alicesw.com"


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def meta(soup, prop_contains):
    # mimic [property$=...] / [property~=...]
    for m in soup.find_all("meta"):
        p = m.get("property", "")
        if prop_contains in p:
            return m.get("content", "")
    return ""


def book_info(url):
    html = get(url)
    soup = BeautifulSoup(html, "html.parser")
    info = {}
    info["name"] = meta(soup, "title")
    info["author"] = meta(soup, "author")
    info["description"] = meta(soup, "description")
    info["cover"] = meta(soup, "image")
    # category / status / update_time
    info["kind"] = " | ".join(
        m.get("content", "")
        for m in soup.find_all("meta")
        if any(k in m.get("property", "") for k in ("category", "status", "update_time"))
    )
    info["lastChapter"] = meta(soup, "latest_chapter_name") or meta(soup, "lastest_chapter_name")
    # toc link: class.opt @ a.2 (3rd <a>) -> href
    opt = soup.select_one(".opt")
    toc_url = ""
    if opt:
        links = opt.find_all("a")
        if len(links) >= 3:
            toc_url = links[2].get("href", "")
    info["tocUrl"] = toc_url
    return info, soup


def toc(toc_url):
    html = get(toc_url)
    soup = BeautifulSoup(html, "html.parser")
    chapters = []
    for a in soup.select(".fix li a"):
        chapters.append({"name": a.get_text(strip=True), "url": a.get("href", "")})
    return chapters


def content(chapter_url):
    html = get(chapter_url)
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one("#chapterContent")
    if not box:
        return None
    paras = [p.get_text("\n", strip=True) for p in box.find_all("p")]
    return "\n".join([t for t in paras if t])


def absu(u):
    if not u:
        return u
    if u.startswith("http"):
        return u
    return BASE + (u if u.startswith("/") else "/" + u)


def main():
    url = "https://www.alicesw.com/novel/44892.html"
    out_path = "test_crawl.txt"

    info, soup = book_info(url)
    name = info["name"]
    author = info["author"]

    toc_url = absu(info["tocUrl"])
    chapters = toc(toc_url) if toc_url else []
    print(f"Book: {name} | author: {author} | chapters: {len(chapters)}")

    lines = []
    # ---- header block (giong origin) ----
    lines.append("=" * 60)
    lines.append(f"  {name}")
    lines.append(f"  {'Tac gia':<8}: {author}")
    lines.append(f"  {'Nguon':<8}: {url}")
    lines.append(f"  {'Chuong':<8}: {len(chapters)}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("")
    lines.append("")

    # ---- per-chapter block ----
    for idx, c in enumerate(chapters, 1):
        cu = absu(c["url"])
        text = content(cu) or "(khong lay duoc noi dung)"
        print(f"  [{idx}/{len(chapters)}] {c['name']} - {len(text)} chars")
        lines.append("─" * 50)
        lines.append(c["name"])
        lines.append("─" * 40)
        lines.append("")
        lines.append(text)
        lines.append("")
        lines.append("")
        time.sleep(0.5)  # tranh request qua nhanh

    with io.open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Saved -> {out_path} ({sum(len(l) for l in lines)} chars)")


if __name__ == "__main__":
    main()
