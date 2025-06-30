import csv
import re
import asyncio
import sys
from playwright.async_api import async_playwright

# === Patterns ===
email_pattern = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
phone_pattern = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
social_patterns = {
    "facebook": re.compile(r"facebook\.com/[^\s\"'<>]+"),
    "instagram": re.compile(r"instagram\.com/[^\s\"'<>]+"),
    "linkedin": re.compile(r"linkedin\.com/[^\s\"'<>]+"),
}

def is_date(string):
    string_clean = string.replace(" ", "")
    if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", string_clean):
        return True
    if re.fullmatch(r"\d{4}[-/]\d{2}", string_clean) or re.fullmatch(r"\d{4}", string_clean):
        return True
    return False

def filter_phones(phones):
    unique_phones = set()
    for phone in phones:
        cleaned = re.sub(r"\s+", " ", phone).strip()
        if is_date(cleaned):
            continue
        if re.match(r"^\d{4}\s*[-–]\s*\d{4}$", cleaned):
            continue
        if re.match(r"(\d\s+){3,}\d", cleaned):
            continue
        digits_only = re.sub(r"\D", "", cleaned)
        if len(digits_only) < 8:
            continue
        unique_phones.add(cleaned)
    return list(unique_phones)

async def extract_contact_info(playwright, url):
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        await page.goto(url, timeout=20000)
        html_content = await page.content()

        html_content = re.sub(r"<(script|style).?>.?</\1>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html_content)

        emails = list(set(email_pattern.findall(text)))
        raw_phones = [match.group().strip() for match in phone_pattern.finditer(text)]
        phones = filter_phones(raw_phones)

        links = await page.eval_on_selector_all("a[href]", "elements => elements.map(el => el.href)")
        socials = {"facebook": "", "instagram": "", "linkedin": ""}
        for link in links:
            for platform, pattern in social_patterns.items():
                if pattern.search(link):
                    socials[platform] = link
                    break

        await browser.close()
        return {
            "email": ", ".join(emails),
            "phone": ", ".join(phones),
            "facebook": socials["facebook"],
            "instagram": socials["instagram"],
            "linkedin": socials["linkedin"]
        }
    except Exception as e:
        print(f"[ERROR] {url}: {e}")
        await browser.close()
        return {
            "email": "",
            "phone": "",
            "facebook": "",
            "instagram": "",
            "linkedin": ""
        }

async def main():
    if len(sys.argv) != 3:
        print("Usage: python web.py <url> <output_csv>")
        return

    url = sys.argv[1]
    output_csv = sys.argv[2]

    if not url.startswith("http"):
        url = "https://" + url

    async with async_playwright() as playwright:
        print(f"[INFO] Scraping: {url}")
        data = await extract_contact_info(playwright, url)

        with open(output_csv, "w", newline='', encoding="utf-8") as outfile:
            writer = csv.writer(outfile)
            writer.writerow(["Website", "Email", "Phone", "Facebook", "Instagram", "LinkedIn"])
            writer.writerow([url, data["email"], data["phone"], data["facebook"], data["instagram"], data["linkedin"]])

    print("✅ Done. Results saved to:", output_csv)

if __name__ == "__main__":
    asyncio.run(main())
