import requests
from bs4 import BeautifulSoup
import sys

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

# Tra URL chuong 197 - ID truyen 12795 (yeu cuoc song)
url = 'https://www.alicesw.com/book/12795/197.html'
print(f"Test URL: {url}")

try:
    resp = requests.get(url, headers=headers, timeout=15)
    print(f'Status: {resp.status_code}')
    print(f'Content length: {len(resp.text)}')
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Kiem tra cac selector chinh
    for sel in ['div.read-content', 'div#content', 'div.content', 'div.chapter-content', 'div#chaptercontent', 'div.booktextdata', 'article']:
        div = soup.select_one(sel)
        if div:
            txt = div.get_text(strip=True)
            print(f'  {sel}: {len(txt)} chars: {txt[:80]}')
        else:
            print(f'  {sel}: KHONG TIM THAY')
    
    h1 = soup.select_one('h1')
    print(f'H1: {h1.get_text(strip=True) if h1 else "NONE"}')
    
    # In danh sach div co nhieu <p>
    print("\n--- DIV co nhieu <p> nhat ---")
    divs_with_p = [(d, len(d.find_all('p')), len(d.get_text(strip=True))) for d in soup.find_all('div')]
    divs_with_p.sort(key=lambda x: -x[1])
    for d, pc, tc in divs_with_p[:5]:
        cls = d.get('class', [])
        id_ = d.get('id', '')
        print(f'  div class={cls} id={id_}: {pc} <p>, {tc} chars')
    
    print("\n--- HTML douan 2000-3500 ---")
    print(resp.text[2000:3500])
    
except Exception as e:
    print(f"LOI: {e}")
