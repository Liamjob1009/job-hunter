import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import os
import json
import re
import time
from urllib.parse import urljoin

# --- הגדרות ---
HISTORY_FILE = "history.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

MY_RESUME = """
Name: Liam Edelman
Location: Tel Aviv, Israel
Looking for: Junior Project Management, Operations, Customer Success, Support.
"""

KEYWORDS_INCLUDE = [
    "Success", "Support", "Care", "Operation", "Project", "Coordinator",
    "Community", "Game", "Junior", "Entry", "Specialist", "QA",
    "Trust", "Product", "Tier", "Analyst", "Manager", "Admin", "Client", "Help"
]

KEYWORDS_EXCLUDE = [
    "Senior", "Head", "Director", "VP", "Chief", "Engineer", "Developer", 
    "DevOps", "Backend", "Frontend", "Full Stack", "Architect", "Legal", "Sales"
]

# --- פונקציות עזר ---

def send_telegram_message(token, chat_id, message):
    if not token or not chat_id: return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = { "chat_id": chat_id, "text": message, "parse_mode": "HTML" }
    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except:
        return False

def load_companies():
    try:
        with open("companies.json", "r") as f: return json.load(f)
    except: return []

def load_history():
    return [] # דיבוג - מתעלמים מהיסטוריה

def save_history(history):
    with open(HISTORY_FILE, "w") as f: json.dump(history, f, indent=2)

# --- פונקציות חיפוש ---

def fetch_greenhouse_jobs(identifier):
    url = f"https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            jobs = []
            for job in data.get("jobs", []):
                jobs.append({
                    "title": job.get("title", "No Title"),
                    "url": job.get("absolute_url", ""),
                    "location": job.get("location", {}).get("name", "Unknown")
                })
            return jobs
    except: pass
    return []

def fetch_comeet_jobs(identifier):
    url = f"https://www.comeet.com/jobs/{identifier}/all"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        jobs = []
        for elem in soup.find_all("a", class_=re.compile("job|position|career", re.I)):
            title = elem.get_text(strip=True)
            href = elem.get("href", "")
            if href and not href.startswith("http"): href = f"https://www.comeet.com{href}"
            if title:
                jobs.append({"title": title, "url": href, "location": "Unknown"})
        return jobs
    except: pass
    return []

def fetch_careers_page_jobs(url, company_name):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        jobs = []
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            if any(kw.lower() in text.lower() for kw in KEYWORDS_INCLUDE):
                job_url = link["href"]
                if not job_url.startswith("
if __name__ == "__main__":
    main()
