import os
import time
import hashlib
import random
import cloudscraper
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fake_useragent import UserAgent
from retrying import retry
try:
    import undetected_chromedriver as uc
    BROWSER_AVAILABLE = True
except ImportError:
    BROWSER_AVAILABLE = False

load_dotenv()

PRODUCT_URLS = [
    "https://www.bol.com/nl/nl/p/-/9300000235555648/",
    "https://www.bol.com/nl/nl/p/me01-mega-evolution-etb-mega-gardevoir/9300000235555646/",
    "https://www.bol.com/nl/nl/p/pokemon-tcg-mega-evolution-6-booster-bundel/9300000235555645/",
    "https://www.bol.com/nl/nl/p/me01-mega-evolution-bo-18ct-display/9300000235555637/",
]

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
LAST_HASH_FILE = ".last_hashes.txt"

ua = UserAgent()

scraper_session = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    delay=10
)


def get_random_headers():
    return {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def fetch_page_with_browser(url):
    if not BROWSER_AVAILABLE:
        raise Exception("Browser fallback not available")
    
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-plugins')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-web-security')
    options.add_argument('--allow-running-insecure-content')
    
    driver = None
    try:
        driver = uc.Chrome(options=options, use_subprocess=True)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        time.sleep(random.uniform(3, 8))
        driver.get(url)
        time.sleep(random.uniform(5, 10))
        
        page_text = driver.page_source.lower()
        if "challenge" in page_text or "checking your browser" in page_text:
            print(f"🛡️ Browser challenge detected, waiting...")
            time.sleep(random.uniform(15, 30))
            page_text = driver.page_source
        
        return driver.page_source
    except Exception as e:
        raise
    finally:
        if driver:
            driver.quit()


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=1000, wait_exponential_max=10000)
def fetch_page(url):
    delay = random.uniform(5, 10)
    print(f"⏳ Sleeping {delay:.1f}s before request to {url}...")
    time.sleep(delay)

    try:
        headers = get_random_headers()
        scraper_session.headers.update(headers)
        r = scraper_session.get(url, timeout=30)
        r.raise_for_status()

        if "challenge" in r.text.lower() or "checking your browser" in r.text.lower():
            return fetch_page_with_browser(url)

        return r.text

    except Exception as cloudscraper_error:
        if "403" in str(cloudscraper_error) or "401" in str(cloudscraper_error):
            try:
                return fetch_page_with_browser(url)
            except Exception as browser_error:
                pass

        time.sleep(random.uniform(10, 20))
        raise cloudscraper_error


def extract_stock_section(html):
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        "div.buy-block",
        "div.buy-block__wrapper",
        "div.buy-block__content",
        "div.offer-panel",
        "div#offer-block",
        "div.offer-container",
        "div.product-offer",
        "div.buy-box"
    ]
    for sel in selectors:
        block = soup.select_one(sel)
        if block:
            return block.get_text(separator=" ", strip=True).lower()
    return soup.get_text(separator=" ", strip=True).lower()


def page_indicates_in_stock(html):
    block_text = extract_stock_section(html)
    return ("in winkelwagen" in block_text or "op voorraad" in block_text) and \
           "tijdelijk niet beschikbaar" not in block_text and \
           "uitverkocht" not in block_text and \
           "niet leverbaar" not in block_text


def send_discord_message(message):
    if not WEBHOOK_URL:
        print("⚠️ No Discord webhook URL configured")
        return
    import requests
    payload = {"content": message}
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to send Discord message: {e}")


def get_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_last_hashes():
    if not os.path.exists(LAST_HASH_FILE):
        return {}
    with open(LAST_HASH_FILE, "r") as f:
        lines = f.readlines()
    return dict(line.strip().split(" ", 1) for line in lines)


def save_hashes(hashes):
    with open(LAST_HASH_FILE, "w") as f:
        for url, h in hashes.items():
            f.write(f"{url} {h}\n")


def main():
    print("🔍 Starting bol.com stock checker...")
    last_hashes = read_last_hashes()

    for url in PRODUCT_URLS:
        try:
            html = fetch_page(url)
            stock_block = extract_stock_section(html)
            current_hash = get_hash(stock_block)
            in_stock = page_indicates_in_stock(html)
            last_hash = last_hashes.get(url)

            if current_hash != last_hash:
                if in_stock:
                    print(f"✅ In stock: {url}")
                    send_discord_message(f"🎉 Product is in stock! <@here>\n{url}")
                else:
                    print(f"⚠️ Stock section changed but product still out of stock: {url}")
                    send_discord_message(f"⚠️ Stock section changed but product is still out of stock:\n{url}")
                last_hashes[url] = current_hash
            else:
                print(f"⏳ Stock section unchanged: {url}")

        except Exception as e:
            print(f"❌ Error checking {url}: {e}")

    save_hashes(last_hashes)
    print("✅ Single run complete.")


if __name__ == "__main__":
    main()
