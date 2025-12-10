import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import os
import json
import re
import time
from urllib.parse import urljoin
import traceback

# --- הגדרות אישיות ---
MY_RESUME = """
Name: Liam Edelman
Location: Tel Aviv, Israel
Looking for: 
1. Junior Project Management / Operations / Coordinator roles.
2. Customer Success / Customer Support / Trust & Safety roles.
Experience:
- Project & Site Manager: Managed end-to-end projects.
- Customer Service (Giraffe): High-pressure environment.
- IDF Recruiter: Data-driven.
Skills: SQL, Excel, Tech-savvy, English (Proficient), Hebrew (Native).
"""

KEYWORDS_INCLUDE = [
    "Success", "Support", "Care", "Operation", "Project", "Coordinator",
    "Community", "Game", "Junior", "Entry", "Specialist", "QA",
    "Trust", "Product", "Tier", "Analyst", "Manager", "Admin", "Client", "Help"
]

KEYWORDS_EXCLUDE = [
    "Senior", "Head", "Director", "VP", "Chief",
    "Engineer", "Developer", "DevOps", "Backend", "Frontend",
    "Full Stack", "Fullstack", "Principal", "Staff", "Architect",
    "Accounting", "Finance", "Legal", "Sales", "R&D"
]

HISTORY_FILE = "history.json"

# --- מפתח הקסם: תחפושת לדפדפן ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

# --- פונקציות עזר ---

def load_companies():
    try:
        with open("companies.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def send_telegram_message(token, chat_id, message):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = { "chat_id": chat_id, "text": message, "parse_mode": "HTML" }
    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except:
        return False

# --- פונקציות חיפוש משופרות ---

def fetch_greenhouse_jobs(identifier):
    url = f"https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            data = response.json()
            jobs = []
            for job in data.get("jobs", []):
                loc_name = job.get("location", {}).get("name", "")
                jobs.append({
                    "title": job.get("title", ""),
                    "url": job.get("absolute_url", ""),
                    "location": loc_name
                })
            return jobs
    except:
        return []
    return []

def fetch_comeet_jobs(identifier):
    url = f"https://www.comeet.com/jobs/{identifier}/all"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            jobs = []
            for elem in soup.find_all("a", class_=re.compile("job|position|career", re.I)):
                title = elem.get_text(strip=True)
                href = elem.get("href", "")
                if href and not href.startswith("http"): href = f"https://www.comeet.com{href}"
                if title:
                    jobs.append({"title": title, "url": href, "location": ""})
            return jobs
    except:
        return []
    return []

def fetch_careers_page_jobs(url, company_name):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            jobs = []
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                if any(kw.lower() in text.lower() for kw in KEYWORDS_INCLUDE):
                    job_url = link["href"]
                    if not job_url.startswith("http"): job_url = urljoin(url, job_url)
                    jobs.append({"title": text, "url": job_url, "location": ""})
            return jobs
    except:
        return []
    return []

def fetch_jobs(company):
    ctype = company.get("type", "")
    if ctype == "greenhouse": return fetch_greenhouse_jobs(company.get("identifier", ""))
    elif ctype == "comeet": return fetch_comeet_jobs(company.get("identifier", ""))
    elif ctype == "careers_page": return fetch_careers_page_jobs(company.get("url", ""), company.get("name", ""))
    return []

def matches_filter(title, location):
    title_lower = title.lower()
    if any(kw.lower() in title_lower for kw in KEYWORDS_EXCLUDE): return False
    if not any(kw.lower() in title_lower for kw in KEYWORDS_INCLUDE): return False
    
    if location and len(location) > 2:
        loc_lower = location.lower()
        is_israel = "israel" in loc_lower or "tel aviv" in loc_lower or "jerusalem" in loc_lower or "herzliya" in loc_lower or "haifa" in loc_lower or "remote" in loc_lower
        if not is_israel:
             if "united states" in loc_lower or "london" in loc_lower or "uk" in loc_lower or "germany" in loc_lower:
                 return False
    return True

def rate_job_with_ai(title, company_name, location, url, model):
    # פרומפט אגרסיבי במיוחד
    prompt = f"""
    You are a lenient job matcher.
    Job: {title} at {company_name} ({location})
    
    INSTRUCTIONS:
    1. IGNORE years of experience. Even if not "Junior", we want to see it.
    2. IF title includes "Support", "Success", "Service", "Help", "Tier", "Specialist": SCORE = 90.
    3. IF title includes "Project", "Coordinator", "Operations", "Admin": SCORE = 85.
    4. ONLY score 0 if it is strictly Engineering/Developer/Finance/Legal.
    
    Return JSON ONLY: {{"score": int, "reason": "very short reason"}}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        result = json.loads(text)
        return result.get("score", 0), result.get("reason", "")
    except:
        return 0, "AI Error"

# --- Main Execution ---

def main():
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w") as f:
            json.dump([], f)

    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    telegram_token = os.environ.get("TELEGRAM_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not gemini_api_key or not telegram_token:
        print("❌ Error: Missing secrets.")
        return

    stats = {"companies": 0, "jobs_scanned": 0, "jobs_filtered_in": 0, "matches_found": 0}

    print("📢 Sending Check Message...")
    send_telegram_message(telegram_token, telegram_chat_id, "🚀 <b>Bot V6 (Nuclear Option)</b>\nSending almost EVERYTHING. Prepare for spam!")

    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    companies = load_companies()
    stats["companies"] = len(companies)
    
    if not companies:
        print("⚠️ No companies found!")
        return
    
    print(f"🔎 Scanning {len(companies)} companies...")
    
    history = load_history()
    
    try:
        for index, company in enumerate(companies):
            company_name = company.get("name", "Unknown")
            print(f"\n🏢 [{index+1}/{len(companies)}] Scanning {company_name}...")
            
            try:
                jobs = fetch_jobs(company)
                stats["jobs_scanned"] += len(jobs)
                
                for job in jobs:
                    title = job.get("title", "")
                    url = job.get("url", "")
                    location = job.get("location", "")
                    job_id = f"{company_name}:{title}"
                    
                    if job_id in history: continue
                    if not matches_filter(title, location): continue
                    
                    stats["jobs_filtered_in"] += 1
                    print(f"   🤖 Evaluating: {title}")
                    score, reason = rate_job_with_ai(title, company_name, location, url, model)
                    
                    history.append(job_id)
                    
                    # --- הורדת הרף לרצפה (15) ---
                    if score >= 15:
                        stats["matches_found"] += 1
                        print(f"   ✅ FOUND ({score})! Sending...")
                        msg = f"🎯 <b>Job Found</b> ({score}/100)\n\n<b>{company_name}</b>\n{title}\n📍 {location}\n\n📝 {reason}\n\n🔗 <a href='{url}'>Link to Job</a>"
                        send_telegram_message(telegram_token, telegram_chat_id, msg)
                        time.sleep(1)
                    else:
                        print(f"   Skipped ({score}): {reason}")
                    
                    time.sleep(1) 
                    
            except Exception as e:
                print(f"⚠️ Error scanning {company_name}: {e}")
                continue 
                
    except Exception as main_error:
        error_msg = f"🚨 <b>CRITICAL ERROR</b>\nThe bot crashed:\n{str(main_error)}"
        send_telegram_message(telegram_token, telegram_chat_id, error_msg)
        print(error_msg)

    save_history(history)
    
    summary_msg = f"""🏁 <b>Scan Complete!</b>
    
📊 <b>Final Stats:</b>
🏢 Companies: {stats['companies']}
🔎 Jobs Scanned: {stats['jobs_scanned']}
🤖 AI Evaluated: {stats['jobs_filtered_in']}
✅ Matches Found: {stats['matches_found']}"""
    
    send_telegram_message(telegram_token, telegram_chat_id, summary_msg)
    print("\n✅ Scan Finished Successfully.")

if __name__ == "__main__":
    main()
