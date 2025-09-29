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

# Initialize user agent rotator
ua = UserAgent()

# Create a cloudscraper session for advanced bot protection bypass
scraper_session = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False
    },
    delay=10  # Add delay for Cloudflare challenges
)

def get_random_headers():
    """Generate realistic browser headers with rotation"""
    return {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def fetch_page_with_browser(url):
    """Fallback method using undetected-chromedriver for advanced bot protection"""
    if not BROWSER_AVAILABLE:
        raise Exception("Browser fallback not available")
        
    print(f"🌐 Using browser fallback for: {url[:50]}...")
    
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')  # Use new headless mode
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-plugins')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-web-security')
    options.add_argument('--allow-running-insecure-content')
    # Removed these as they cause errors:
    # options.add_experimental_option("excludeSwitches", ["enable-automation"])
    # options.add_experimental_option('useAutomationExtension', False)
    
    driver = None
    try:
        # Let undetected-chromedriver auto-detect the Chrome binary
        driver = uc.Chrome(options=options, use_subprocess=True)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Random human-like delay
        time.sleep(random.uniform(3, 8))
        
        driver.get(url)
        
        # Wait for page to load and check for challenges
        time.sleep(random.uniform(5, 10))
        
        # Check if we're being challenged
        page_text = driver.page_source.lower()
        if "challenge" in page_text or "checking your browser" in page_text:
            print(f"🛡️ Browser challenge detected, waiting...")
            time.sleep(random.uniform(15, 30))
            page_text = driver.page_source
            
        print(f"✅ Browser successfully fetched: {url[:50]}...")
        return driver.page_source
        
    except Exception as e:
        print(f"❌ Browser error for {url}: {e}")
        raise
    finally:
        if driver:
            driver.quit()


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=1000, wait_exponential_max=10000)
def fetch_page(url):
    """Fetch page with advanced bot protection bypass and browser fallback"""
    # Random delay to mimic human behavior
    delay = random.uniform(5, 10)
    print(f"⏳ Sleeping {delay:.1f}s before request to {url}...")
    time.sleep(delay)
    
    # First, try cloudscraper approach
    try:
        # Update session headers for this request
        headers = get_random_headers()
        scraper_session.headers.update(headers)
        
        r = scraper_session.get(url, timeout=30)
        r.raise_for_status()
        
        # Check if we got a challenge page
        if "challenge" in r.text.lower() or "checking your browser" in r.text.lower():
            print(f"🛡️ CloudScraper challenge detected, trying browser fallback...")
            return fetch_page_with_browser(url)
            
        print(f"✅ [CLOUDSCRAPER] Fetched page for {url[:50]} (len={len(r.text)})")
        return r.text
        
    except Exception as cloudscraper_error:
        print(f"❌ [CLOUDSCRAPER] Failed for {url}: {cloudscraper_error}")
        
        # If cloudscraper fails with 403 or 401, try browser fallback
        if "403" in str(cloudscraper_error) or "401" in str(cloudscraper_error):
            try:
                print(f"🔄 Trying browser fallback due to {cloudscraper_error}...")
                return fetch_page_with_browser(url)
            except Exception as browser_error:
                print(f"❌ Browser fallback also failed: {browser_error}")
                
        # Add longer delay before retry
        time.sleep(random.uniform(10, 20))
        raise cloudscraper_error


def page_indicates_in_stock(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text().lower()
    return "op voorraad" in text and "tijdelijk niet beschikbaar" not in text and "uitverkocht" not in text


def send_discord_message(message):
    if not WEBHOOK_URL:
        print("⚠️ No Discord webhook URL configured")
        return
    payload = {"content": message}
    # Use a separate simple session for Discord webhook
    import requests
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

    while True:
        for url in PRODUCT_URLS:
            try:
                html = fetch_page(url)
                current_hash = get_hash(html)
                in_stock = page_indicates_in_stock(html)
                last_hash = last_hashes.get(url)

                if in_stock and current_hash != last_hash:
                    print(f"✅ In stock: {url}")
                    send_discord_message(
                        f"🎉 Product is in stock! <@here>\n{url}")
                    last_hashes[url] = current_hash
                else:
                    print(f"⏳ Not in stock or unchanged: {url}")
            except Exception as e:
                print(f"❌ Error checking {url}: {e}")

        save_hashes(last_hashes)
        print(f"⏳ Sleeping {INTERVAL} seconds before next check...")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
