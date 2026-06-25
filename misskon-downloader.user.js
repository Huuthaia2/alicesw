// ==UserScript==
// @name         Misskon Image Downloader
// @namespace    http://tampermonkey.net/
// @version      2.0
// @description  Download all images from misskon.com gallery pages (multi-page support)
// @author       User
// @match        https://misskon.com/*
// @grant        GM_download
// @grant        GM_xmlhttpRequest
// @connect      misskon.com
// @connect      *
// ==/UserScript==

(function () {
    'use strict';

    // ── URL helpers ──────────────────────────────────────────────────────────
    const IMG_EXT  = /\.(jpe?g|png|webp|gif)(\?[^"']*)?$/i;
    const IMG_PATH = /\/(upload|wp-content|photo|image|img|pic|file|media|cdn)\//i;
    const SKIP     = /\/(icon|logo|avatar|banner|spinner|loading|pixel|blank|spacer|ads?)\//i;

    function isImageUrl(u) {
        if (!u || u.startsWith('data:') || u.startsWith('blob:')) return false;
        return (IMG_EXT.test(u) || IMG_PATH.test(u)) && !SKIP.test(u);
    }

    function normalizeUrl(u) {
        try { return new URL(u, location.href).href; } catch { return null; }
    }

    // ── Extract images from an HTML string (or live document) ────────────────
    function extractImages(doc) {
        const seen = new Set();
        const urls = [];

        const add = (u) => {
            u = normalizeUrl(u);
            if (u && !seen.has(u) && isImageUrl(u)) { seen.add(u); urls.push(u); }
        };

        // <a href>
        doc.querySelectorAll('a[href]').forEach(a => add(a.getAttribute('href')));

        // <img> — every possible lazy-load attribute
        doc.querySelectorAll('img').forEach(img => {
            ['src','data-src','data-lazy-src','data-original','data-full-url',
             'data-large','data-image','data-url','data-link','data-original-src']
                .forEach(attr => { const v = img.getAttribute(attr); if (v) add(v); });
            if (img.srcset) img.srcset.split(',').forEach(s => add(s.trim().split(/\s+/)[0]));
            Array.from(img.attributes).forEach(a => {
                if (a.name.startsWith('data-') && isImageUrl(a.value)) add(a.value);
            });
        });

        // <a data-*> lightbox attributes
        doc.querySelectorAll('a').forEach(a => {
            Array.from(a.attributes).forEach(attr => {
                if (attr.name.startsWith('data-') && isImageUrl(attr.value)) add(attr.value);
            });
        });

        // <noscript>
        doc.querySelectorAll('noscript').forEach(ns => {
            (ns.textContent.match(/src=["']([^"']+)/g) || [])
                .forEach(s => add(s.replace(/src=["']/, '')));
        });

        // De-thumbnail: remove -150x150 suffixes, dedupe by base
        const deduped = [];
        const baseSeen = new Set();
        for (const u of urls) {
            const base = u.replace(/-\d+x\d+(\.\w+(\?.*)?$)/, '$1');
            if (!baseSeen.has(base)) { baseSeen.add(base); deduped.push(base); }
        }
        return deduped;
    }

    // ── Find pagination URLs for this post ───────────────────────────────────
    function getPaginationUrls() {
        const pages = new Set();

        // WordPress /?page=N or /page/N/ or appended /2/ on the post URL
        document.querySelectorAll('a.page-numbers, a[href*="page="], .wp-pagenavi a, .pagination a, nav a').forEach(a => {
            const href = a.href;
            if (href && href.includes(location.hostname)) pages.add(href);
        });

        // Also detect numeric page links relative to the current URL
        const base = location.href.replace(/\/page\/\d+\/?/, '/').replace(/\/$/, '');
        document.querySelectorAll('a').forEach(a => {
            const m = a.href && a.href.match(/\/page\/(\d+)\/?/);
            if (m) pages.add(`${base}/page/${m[1]}/`);
        });

        // Remove current page from the list
        pages.delete(location.href);
        pages.delete(location.href.replace(/\/$/, ''));
        return [...pages];
    }

    // ── Fetch a remote page and parse its DOM ────────────────────────────────
    function fetchPage(url) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: 'GET',
                url,
                onload(resp) {
                    const parser = new DOMParser();
                    resolve(parser.parseFromString(resp.responseText, 'text/html'));
                },
                onerror: reject,
                ontimeout: reject,
                timeout: 20000,
            });
        });
    }

    // ── Folder name ──────────────────────────────────────────────────────────
    function baseFolder() {
        return document.title
            .replace(/\s*[-–|].*$/, '').trim()
            .replace(/[\\/:*?"<>|]/g, '_')
            .substring(0, 80) || 'misskon';
    }

    // ── UI ───────────────────────────────────────────────────────────────────
    function buildUI() {
        const panel = document.createElement('div');
        Object.assign(panel.style, {
            position: 'fixed', top: '80px', right: '16px', zIndex: 2147483647,
            background: '#1a1a2e', color: '#eee', borderRadius: '10px',
            padding: '14px 18px', fontFamily: 'sans-serif', fontSize: '13px',
            boxShadow: '0 4px 24px rgba(0,0,0,.8)', minWidth: '240px',
        });
        panel.innerHTML = `
          <button id="mk-close" style="position:absolute;top:8px;right:10px;background:none;border:none;color:#aaa;cursor:pointer;font-size:16px">✕</button>
          <div style="font-weight:bold;margin-bottom:10px;font-size:14px">📷 Misskon Downloader</div>
          <div id="mk-info" style="margin-bottom:8px;line-height:1.4">Đang quét…</div>
          <div style="height:6px;background:#333;border-radius:3px;margin-bottom:10px;overflow:hidden">
            <div id="mk-bar" style="height:100%;width:0%;background:#4ecca3;border-radius:3px;transition:width .3s"></div>
          </div>
          <button id="mk-scan" style="background:#444;color:#eee;border:none;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px;width:100%;margin-bottom:6px">🔄 Quét lại tất cả trang</button>
          <button id="mk-dl" style="background:#4ecca3;color:#1a1a2e;border:none;border-radius:6px;padding:7px 14px;cursor:pointer;font-weight:bold;width:100%;font-size:13px" disabled>⬇ Tải tất cả</button>
        `;
        document.body.appendChild(panel);
        panel.querySelector('#mk-close').onclick = () => panel.remove();
        return {
            info:    panel.querySelector('#mk-info'),
            bar:     panel.querySelector('#mk-bar'),
            btnDl:   panel.querySelector('#mk-dl'),
            btnScan: panel.querySelector('#mk-scan'),
        };
    }

    // ── Download one ─────────────────────────────────────────────────────────
    function downloadOne(url, name) {
        return new Promise(resolve => {
            GM_download({
                url, name,
                onload:    resolve,
                onerror:   (e) => { console.warn('[MK]', url, e); resolve(); },
                ontimeout: resolve,
            });
        });
    }

    // ── Main ─────────────────────────────────────────────────────────────────
    async function main() {
        const { info, bar, btnDl, btnScan } = buildUI();
        let allUrls = [];

        async function scan() {
            btnDl.disabled = true;
            btnScan.disabled = true;
            bar.style.width = '0%';

            // Page 1 — current document
            const page1 = extractImages(document);
            const paginationUrls = getPaginationUrls();

            info.textContent = `Trang hiện tại: ${page1.length} ảnh. Đang quét ${paginationUrls.length} trang còn lại…`;
            console.log('[MK] pagination pages:', paginationUrls);

            const otherImages = [];
            for (let i = 0; i < paginationUrls.length; i++) {
                info.textContent = `Quét trang ${i + 2} / ${paginationUrls.length + 1}…`;
                try {
                    const doc = await fetchPage(paginationUrls[i]);
                    const imgs = extractImages(doc);
                    console.log(`[MK] page ${i+2}: ${imgs.length} images`);
                    otherImages.push(...imgs);
                } catch (e) {
                    console.warn('[MK] failed to fetch', paginationUrls[i], e);
                }
                await new Promise(r => setTimeout(r, 300));
            }

            // Merge + global dedupe
            const merged = new Set([...page1, ...otherImages]);
            allUrls = [...merged];

            if (allUrls.length === 0) {
                info.textContent = '⚠ Không thấy ảnh. Cuộn trang rồi "Quét lại".';
            } else {
                info.textContent = `✅ Tổng: ${allUrls.length} ảnh (${paginationUrls.length + 1} trang).`;
                btnDl.disabled = false;
            }
            btnScan.disabled = false;
        }

        btnScan.onclick = scan;

        btnDl.onclick = async () => {
            btnDl.disabled = true;
            btnScan.disabled = true;
            const folder = baseFolder();

            for (let i = 0; i < allUrls.length; i++) {
                const url = allUrls[i];
                const extM = url.match(/\.(jpe?g|png|webp|gif)/i);
                const ext = extM ? extM[0].toLowerCase().replace('jpeg','jpg') : '.jpg';
                const filename = `${folder}/${String(i + 1).padStart(3, '0')}${ext}`;

                info.textContent = `Tải ${i + 1} / ${allUrls.length}…`;
                bar.style.width = `${Math.round(((i + 1) / allUrls.length) * 100)}%`;

                await downloadOne(url, filename);
                await new Promise(r => setTimeout(r, 250));
            }

            info.textContent = `✅ Hoàn tất! ${allUrls.length} ảnh.`;
            bar.style.width = '100%';
            btnDl.textContent = '✅ Xong';
            btnScan.disabled = false;
        };

        // Auto-scan after page settles
        setTimeout(scan, 1500);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', main);
    } else {
        main();
    }
})();
