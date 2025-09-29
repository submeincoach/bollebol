#!/usr/bin/env python3
import os
import time
import hashlib
import random
import traceback
import cloudscraper
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fake_useragent import UserAgent
from retrying import retry

# Try to import undetected_chromedriver; if not installed we fallback gracefully
try:
    import undetected_chromedriver as uc
    BROWSER_AVAILABLE = True
except Exception:
    BROWSER_AVAILABLE = False

load_dotenv()

# ---------------- CONFIG ----------------
PRODUCT_URLS = [
    "https://www.bol.com/nl/nl/p/-/9300000235555648/",
    "https://www.bol.com/nl/nl/p/me01-mega-evolution-etb-mega-gardevoir/9300000235555646/",
    "https://www.bol.com/nl/nl/p/pokemon-tcg-mega-evolution-6-booster-bundel/9300000235555645/",
    "https://www.bol.com/nl/nl/p/me01-mega-evolution-bo-18ct-display/9300000235555637/",
]

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
LAST_HASH_FILE = os.getenv("LAST_HASH_FILE", ".last_hashes.txt")
# If RUN_ONCE is "1" or "true" (case-insensitive) the script will run once and exit:
RUN_ONCE = os.getenv("RUN_ONCE", "false").lower() in ("1", "true", "yes")
# ----------------------------------------

ua = UserAgent()

# Build a cloudscraper session. cloudflare/Akamai challenges are common on bol.com.
scraper_session = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False
    },
    delay=10  # give cloudscraper a small delay if challenge appears
)


def get_random_headers():
    """Return realistic rotating headers."""
    return {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.bol.com/",
        "Cache-Control": "max-age=0"
    }


def fetch_page_with_browser(url):
    """Fetch the page using undetected_chromedriver (headless) to bypass JS challenges."""
    if not BROWSER_AVAILABLE:
        raise Exception("undetected_chromedriver is not available in the environment")

    print(f"🌐 [BROWSER] Using browser fallback for: {url}")
    options = uc.ChromeOptions()
    # headless=new is recommended for newer Chrome versions; fallbacks possible
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    # Make automation less detectable
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    driver = None
    try:
        driver = uc.Chrome(options=options, use_subprocess=True)
        # Try to hide webdriver property
        try:
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception:
            pass

        # Short random delay to mimic human behavior
        time.sleep(random.uniform(1.5, 4.5))
        driver.get(url)

        # Wait for the page to load JS; adjust sleep if needed or add explicit waits
        time.sleep(random.uniform(3.5, 8.0))
        page_source = driver.page_source
        text_lower = page_source.lower()

        # If a challenge message exists, wait a bit and re-evaluate
        if "checking your browser" in text_lower or "challenge" in text_lower or "proxy" in text_lower:
            print("🛡 Detected challenge page in browser; waiting then reloading...")
            time.sleep(random.uniform(10, 20))
            driver.refresh()
            time.sleep(random.uniform(3, 7))
            page_source = driver.page_source

        print(f"✅ [BROWSER] Fetched page for {url[:60]}...")
        return page_source

    except Exception as e:
        print(f"❌ [BROWSER] Error fetching {url}: {e}")
        # bubble up exception after printing stack for debugging
        traceback.print_exc()
        raise
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=1000, wait_exponential_max=10000)
def fetch_page(url):
    """Attempt to fetch using cloudscraper first, fallback to browser when necessary."""
    delay = random.uniform(1.5, 6.0)
    print(f"⏳ Sleeping {delay:.1f}s before request to {url[:60]}...")
    time.sleep(delay)

    headers = get_random_headers()
    # update cloudscraper session headers for the individual request
    scraper_session.headers.update(headers)

    try:
        r = scraper_session.get(url, timeout=30)
        status = getattr(r, "status_code", None)
        if status and status >= 400:
            # raise an HTTPError to trigger fallback or retry
            raise Exception(f"HTTP {status}")

        # Detect challenge pages in returned HTML
        text_lower = (r.text or "").lower()
        if "checking your browser" in text_lower or "please enable javascript" in text_lower or "challenge" in text_lower:
            print("🛡 CloudScraper detected challenge page content; falling back to browser.")
            # use browser fallback to get real content
            return fetch_page_with_browser(url)

        print(f"✅ [CLOUDSCRAPER] Fetched page for {url[:60]} (len={len(r.text)})")
        return r.text

    except Exception as cloudscraper_error:
        err_str = str(cloudscraper_error)
        print(f"❌ [CLOUDSCRAPER] Failed for {url}: {err_str}")
        # If it looks like a 403 or 'forbidden', try browser fallback
        if "403" in err_str or "Forbidden" in err_str or "http 403" in err_str.lower():
            if BROWSER_AVAILABLE:
                try:
                    print("🔁 Detected 403 — attempting browser fallback...")
                    return fetch_page_with_browser(url)
                except Exception as be:
                    print(f"❌ Browser fallback error after 403: {be}")
            else:
                print("⚠ Browser fallback not available; consider installing undetected-chromedriver or run locally.")
        # re-raise to trigger retrying (or final failure)
        raise


def page_indicates_in_stock(html):
    """Return True if page HTML indicates availability."""
    if not html:
        return False
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ").lower()
    # check typical Dutch phrases used on bol for availability vs sold out
    if any(x in text for x in ["uitverkocht", "tijdelijk niet leverbaar", "moment niet leverbaar", "niet leverbaar"]):
        return False
    # check possible availability phrases
    if "op voorraad" in text or "direct leverbaar" in text or "beschikbaar" in text:
        return True
    # fallback: if page contains buttons like "in winkelwagen" or "bestellen", it may be available
    if "in winkelwagen" in text or "bestellen" in text:
        return True
    return False


def send_discord_message(message):
    if not WEBHOOK_URL:
        print("⚠ No WEBHOOK_URL configured; skipping Discord send.")
        return
    import requests
    try:
        payload = {"content": message}
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
        print("✅ Sent Discord message.")
    except Exception as e:
        print(f"❌ Failed to send Discord message: {e}")


def get_hash(content):
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def read_last_hashes():
    if not os.path.exists(LAST_HASH_FILE):
        return {}
    out = {}
    try:
        with open(LAST_HASH_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    url, h = line.split(" ", 1)
                    out[url] = h
                except ValueError:
                    continue
    except Exception:
        pass
    return out


def save_hashes(hashes):
    try:
        with open(LAST_HASH_FILE, "w", encoding="utf-8") as f:
            for url, h in hashes.items():
                f.write(f"{url} {h}\n")
    except Exception as e:
        print(f"⚠ Failed to save hashes: {e}")


def check_all_once(last_hashes):
    """Check all products once and return updated last_hashes."""
    for url in PRODUCT_URLS:
        try:
            html = fetch_page(url)
            current_hash = get_hash(html)
            in_stock = page_indicates_in_stock(html)
            last_hash = last_hashes.get(url)

            if in_stock and current_hash != last_hash:
                print(f"🎉 [ALERT] In stock and changed: {url}")
                send_discord_message(f"🎉 Product in stock! {url}")
                last_hashes[url] = current_hash
            else:
                print(f"⏳ Not in stock or unchanged: {url}")
                # update hash so we reduce repeated alerts if desired (optional)
                if last_hash is None:
                    last_hashes[url] = current_hash
        except Exception as e:
            print(f"❌ Error checking {url}: {e}")
            traceback.print_exc()
    return last_hashes


def main():
    print("🔍 Starting bol.com stock checker...")
    last_hashes = read_last_hashes()

    # If single-run mode (useful for GitHub Actions), run once and exit
    if RUN_ONCE:
        print("▶ Running in single-run mode (RUN_ONCE enabled).")
        new_hashes = check_all_once(last_hashes)
        save_hashes(new_hashes)
        print("✅ Single-run complete.")
        return

    # otherwise run continuously
    while True:
        new_hashes = check_all_once(last_hashes)
        save_hashes(new_hashes)
        print(f"⏲ Sleeping for {INTERVAL} seconds...\n")
        time.sleep(INTERVAL)
        last_hashes = new_hashes


if __name__ == "__main__":
    main()
