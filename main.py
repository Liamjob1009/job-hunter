import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import os
import json
import re
import time
from urllib.parse import urljoin

KEYWORDS_INCLUDE = [
    "Success", "Support", "Care", "Fraud", "Risk", "Operation", 
    "Community", "Game", "Junior", "Entry", "Specialist", "QA",
    "Quality", "Trust", "Product"
]

KEYWORDS_EXCLUDE = [
    "Senior", "Head", "Director", "Lead", "VP", "Manager", 
    "Engineer", "Developer", "DevOps", "Backend", "Frontend",
    "Full Stack", "Fullstack", "Principal", "Staff", "Architect"
]

HISTORY_FILE = "history.json"


def load_companies():
    with open("companies.json", "r") as f:
        return json.load(f)


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def fetch_greenhouse_jobs(identifier):
    url = f"https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            jobs = []
            for job in data.get("jobs", []):
                jobs.append({
                    "title": job.get("title", ""),
                    "url": job.get("absolute_url", ""),
                    "location": job.get("location", {}).get("name", "")
                })
            return jobs
    except Exception as e:
        print(f"Error fetching Greenhouse jobs for {identifier}: {e}")
    return []


def fetch_comeet_jobs(identifier):
    url = f"https://www.comeet.com/jobs/{identifier}/all"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            jobs = []
            job_elements = soup.find_all("a", class_=re.compile("job|position|career", re.I))
            if not job_elements:
                job_elements = soup.find_all("div", class_=re.compile("job|position|career", re.I))
            for elem in job_elements:
                title = elem.get_text(strip=True)
                href = elem.get("href", "")
                if href and not href.startswith("http"):
                    href = f"https://www.comeet.com{href}"
                if title:
                    jobs.append({
                        "title": title,
                        "url": href,
                        "location": ""
                    })
            return jobs
    except Exception as e:
        print(f"Error fetching Comeet jobs for {identifier}: {e}")
    return []


def fetch_careers_page_jobs(url, company_name):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            jobs = []
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                if any(kw.lower() in text.lower() for kw in KEYWORDS_INCLUDE):
                    job_url = link["href"]
                    if not job_url.startswith("http"):
                        job_url = urljoin(url, job_url)
                    jobs.append({
                        "title": text,
                        "url": job_url,
                        "location": ""
                    })
            return jobs
    except Exception as e:
        print(f"Error fetching careers page for {company_name}: {e}")
    return []


def fetch_jobs(company):
    company_type = company.get("type", "")
    if company_type == "greenhouse":
        return fetch_greenhouse_jobs(company.get("identifier", ""))
    elif company_type == "comeet":
        return fetch_comeet_jobs(company.get("identifier", ""))
    elif company_type == "careers_page":
        return fetch_careers_page_jobs(company.get("url", ""), company.get("name", ""))
    return []


def matches_filter(title):
    title_lower = title.lower()
    has_include = any(kw.lower() in title_lower for kw in KEYWORDS_INCLUDE)
    has_exclude = any(kw.lower() in title_lower for kw in KEYWORDS_EXCLUDE)
    return has_include and not has_exclude


def rate_job_with_ai(title, company_name, model):
    prompt = f"""I am a gamer looking for entry-level tech roles (Support, CS, Ops). 
Rate this job '{title}' at '{company_name}' from 0-100. 
Be generous if it relates to gaming.
Return JSON only: {{"score": int, "reason": "str"}}"""
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        result = json.loads(text)
        return result.get("score", 0), result.get("reason", "")
    except Exception as e:
        print(f"Error rating job '{title}': {e}")
        return 50, "Could not rate job"


def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return False


def main():
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    telegram_token = os.environ.get("TELEGRAM_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not gemini_api_key:
        print("Error: GEMINI_API_KEY environment variable not set")
        return
    
    if not telegram_token or not telegram_chat_id:
        print("Warning: Telegram credentials not set. Will skip sending alerts.")
    
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    companies = load_companies()
    history = load_history()
    new_jobs_found = 0
    alerts_sent = 0
    
    print(f"Starting job scan for {len(companies)} companies...")
    
    for company in companies:
        company_name = company.get("name", "Unknown")
        print(f"\nScanning {company_name}...")
        
        jobs = fetch_jobs(company)
        print(f"  Found {len(jobs)} total jobs")
        
        for job in jobs:
            title = job.get("title", "")
            url = job.get("url", "")
            
            job_id = f"{company_name}:{title}:{url}"
            if job_id in history:
                continue
            
            if not matches_filter(title):
                continue
            
            print(f"  Evaluating: {title}")
            new_jobs_found += 1
            
            score, reason = rate_job_with_ai(title, company_name, model)
            print(f"    Score: {score} - {reason}")
            
            history.append(job_id)
            
            if score > 75 and telegram_token and telegram_chat_id:
                message = f"""🎮 <b>New Job Alert!</b>

<b>Company:</b> {company_name}
<b>Role:</b> {title}
<b>Score:</b> {score}/100

<b>Why:</b> {reason}

<a href="{url}">Apply Here</a>"""
                
                if send_telegram_message(telegram_token, telegram_chat_id, message):
                    alerts_sent += 1
                    print(f"    Alert sent!")
            
            time.sleep(1)
    
    save_history(history)
    
    print(f"\n{'='*50}")
    print(f"Scan complete!")
    print(f"New matching jobs found: {new_jobs_found}")
    print(f"Alerts sent: {alerts_sent}")
    print(f"Total jobs in history: {len(history)}")


if __name__ == "__main__":
    main()
