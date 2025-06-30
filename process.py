import csv
import re
import asyncio
import sys
import pandas as pd
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright, Browser

# === Patterns ===
email_pattern = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
phone_pattern = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
social_patterns = {
    "facebook": re.compile(r"facebook\.com/[^\s\"'<>]+"),
    "instagram": re.compile(r"instagram\.com/[^\s\"'<>]+"),
    "linkedin": re.compile(r"linkedin\.com/[^\s\"'<>]+"),
}

def is_date(string):
    string_clean = str(string).replace(" ", "")
    if len(string_clean) > 10:
        return False
    if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", string_clean):
        return True
    if re.fullmatch(r"\d{4}[-/]\d{2}", string_clean) or re.fullmatch(r"\d{4}", string_clean):
        return True
    return False

def clean_phone(phone):
    return "".join(filter(str.isdigit, phone))

def is_valid_url(url):
    parsed = urlparse(url)
    return bool(parsed.scheme and parsed.netloc)

async def get_contact_info(browser: Browser, url: str):
    if not url.startswith("http"):
        url = "https://" + url

    if not is_valid_url(url):
        print(f"[INVALID] Skipping malformed URL: {url}", file=sys.stderr)
        return {"url": url, "emails": "", "phones": "", "facebook": "", "instagram": "", "linkedin": ""}

    page = None
    try:
        page = await browser.new_page()
        # Go to the initial page and wait for all network activity to settle
        await page.goto(url, timeout=30000, wait_until="networkidle")

        # --- Try to find and navigate to a contact page ---
        try:
            # Use a case-insensitive text selector to find a link with 'contact', 'about', or 'support'
            contact_link_locator = page.locator("a:text-matches('contact|about|support', 'i')").first
            contact_href = await contact_link_locator.get_attribute('href', timeout=2000)
            if contact_href:
                contact_url = urljoin(url, contact_href)
                print(f"[INFO] {url}: Found contact page, navigating to {contact_url}", file=sys.stderr)
                # Navigate to the contact page and wait for it to settle
                await page.goto(contact_url, timeout=30000, wait_until="networkidle")
        except Exception:
            print(f"[DEBUG] {url}: No contact page found or failed to navigate. Scraping current page.", file=sys.stderr)
        # --- End of contact page logic ---

        content = await page.content()

        # Extract emails and phones
        emails = set(email_pattern.findall(content))
        phones = set(phone_pattern.findall(content))
        print(f"[DEBUG] {url}: Found {len(emails)} emails, {len(phones)} raw phone numbers.", file=sys.stderr)
        cleaned_phones = {clean_phone(p) for p in phones if not is_date(p)}

        # Filter unique phone numbers
        unique_phones = set()
        for phone in sorted(cleaned_phones, key=len, reverse=True):
            if not any(phone in p for p in unique_phones):
                unique_phones.add(phone)

        # Extract social media links from <a href>
        links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        socials = {"facebook": "", "instagram": "", "linkedin": ""}
        for link in links:
            for platform, pattern in social_patterns.items():
                if pattern.search(link) and socials[platform] == "":
                    socials[platform] = link

        return {"url": url, "emails": ", ".join(emails), "phones": ", ".join(unique_phones), **socials}
    except Exception as e:
        print(f"[ERROR] {url}: An error occurred during scraping. Saving debug files.", file=sys.stderr)
        print(f"  - Exception: {e}", file=sys.stderr)
        try:
            # Save a screenshot and the HTML for debugging
            screenshot_path = "error_screenshot.png"
            html_path = "error_page.html"
            if page and not page.is_closed():
                await page.screenshot(path=screenshot_path)
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(await page.content())
                print(f"  - Saved screenshot to {screenshot_path}", file=sys.stderr)
                print(f"  - Saved HTML to {html_path}", file=sys.stderr)
        except Exception as debug_e:
            print(f"  - Failed to save debug files: {debug_e}", file=sys.stderr)
        return {"url": url, "emails": "", "phones": "", "facebook": "", "instagram": "", "linkedin": ""}
    finally:
        if page and not page.is_closed():
            await page.close()

async def main(input_file: str, output_file: str):
    try:
        # Use pandas to read either CSV or Excel, robustly
        try:
            df = pd.read_csv(input_file, on_bad_lines='skip', encoding='utf-8')
        except (UnicodeDecodeError, pd.errors.ParserError):
            df = pd.read_excel(input_file)

        # --- Intelligent Column Finding --- 
        url_column = None
        max_score = -1

        # Analyze columns to find the one with URLs or emails
        for col in df.columns:
            score = 0
            # Sample up to 20 non-empty rows to determine column type
            samples = df[col].dropna().head(20)
            if samples.empty:
                continue
            
            for sample in samples:
                s = str(sample).lower()
                # Heuristic: score based on content
                if '@' in s or '.com' in s or any(tld in s for tld in ['.net', '.org', '.io', '.co']):
                    score += 1
            
            if score > max_score:
                max_score = score
                url_column = col

        if url_column is None or max_score == 0:
            print("Could not identify a column containing URLs or emails.", file=sys.stderr)
            sys.exit(1)

        print(f"[INFO] Identified '{url_column}' as the column containing URLs/emails.", file=sys.stderr)

        # --- URL/Domain Extraction ---
        # Extract values, clean them, and remove duplicates
        values = df[url_column].dropna().astype(str).str.strip().tolist()
        
        urls = []
        seen = set()
        for v in values:
            if not v:
                continue
            
            if '@' in v:
                # It's an email, extract the domain
                domain = v.split('@')[-1]
                if domain and domain not in seen:
                    urls.append(domain)
                    seen.add(domain)
            elif '.' in v and ' ' not in v.strip():
                # It's likely a URL/domain. Add validation.
                parts = v.split('.')
                # A valid domain should have at least two parts (e.g., 'domain.com')
                # and the part before the first dot must not be empty.
                if len(parts) >= 2 and parts[0]:
                    if v not in seen:
                        urls.append(v)
                        seen.add(v)
        print(f"[INFO] Extracted {len(urls)} unique domains/URLs to process.", file=sys.stderr)

    except FileNotFoundError:
        print(f"File not found: {input_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading input file. It might be corrupted or in an unsupported format. Details: {e}", file=sys.stderr)
        sys.exit(1)

    if not urls:
        print("No URLs or emails found in the identified column.", file=sys.stderr)
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        results = []
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] Scraping: {url}")
            result = await get_contact_info(browser, url)
            results.append(result)
        await browser.close()

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["url", "emails", "phones", "facebook", "instagram", "linkedin"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone. Scraped {len(results)} websites. Results saved to: {output_file}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python process.py <input_csv> <output_csv>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    try:
        asyncio.run(main(input_path, output_path))
    except Exception as e:
        # Final catch-all to ensure any and all errors are reported with details.
        import traceback
        print(f"A fatal, unhandled error occurred in process.py: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)