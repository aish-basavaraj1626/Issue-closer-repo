import os
import json
import requests
from datetime import datetime, timedelta
from dateutil.parser import parse as parse_date

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("REPO")

if not GITHUB_TOKEN or not REPO or "/" not in REPO:
    raise Exception("❌ GITHUB_TOKEN or REPO environment variable not set or invalid format.")

REPO_OWNER, REPO_NAME = REPO.strip().split("/")
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

REQUIRED_PRIMARY_LABEL = "Normal Change Request"
REQUIRED_SECONDARY_LABELS = {"Application", "Infrastructure"}
LABELS_TO_ADD_ON_CLOSE = ["done", "Resolution/Done"]

REQUIRED_CHECKLIST = {
    "assessed", "authorized", "scheduled", "implemented", "reviewed"
}

def get_issues():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues"
    params = {
        "state": "open",
        "labels": REQUIRED_PRIMARY_LABEL,
        "per_page": 100
    }
    response = requests.get(url, headers=HEADERS, params=params)
    response.raise_for_status()
    return response.json()

def get_issue_comments(issue_number):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()

def has_required_checklist(comments):
    normalized = set()
    for comment in comments:
        for line in comment["body"].splitlines():
            line = line.strip().lower()
            if "✔" in line or "✓" in line:
                for keyword in REQUIRED_CHECKLIST:
                    if keyword in line:
                        normalized.add(keyword)
    print(f"📋 Found normalized checklist: {normalized}")
    return REQUIRED_CHECKLIST.issubset(normalized)

def add_labels(issue_number, labels):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/labels"
    response = requests.post(url, headers=HEADERS, json={"labels": labels})
    response.raise_for_status()

def close_issue(issue_number):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    response = requests.patch(url, headers=HEADERS, json={"state": "closed"})
    response.raise_for_status()

def main():
    issues = get_issues()
    print(f"\n🔍 Found {len(issues)} open issues\n")
    closed_issues = []

    for issue in issues:
        issue_number = issue["number"]
        title = issue["title"]
        created_at = parse_date(issue["created_at"])
        labels = {label["name"] for label in issue.get("labels", [])}

        print(f"➡️ #{issue_number}: {title}")
        print(f"   📆 Created on: {created_at.date()}")
        print(f"   🏷️ Labels: {labels}")

        if REQUIRED_PRIMARY_LABEL not in labels:
            print("⏩ Skipped: missing 'Normal Change Request' label\n")
            continue

        if not labels & REQUIRED_SECONDARY_LABELS:
            print("⏩ Skipped: missing secondary label 'Application' or 'Infrastructure'\n")
            continue

        if "done" in labels:
            print("⏩ Skipped: already closed with 'done' label\n")
            continue

        if not has_required_checklist(get_issue_comments(issue_number)):
            print("⏩ Skipped: Checklist not complete\n")
            continue

        # ✅ SKIPPING PROJECT STATUS CHECK FOR NOW
        print(f"✅ Closing issue #{issue_number} and adding labels: {LABELS_TO_ADD_ON_CLOSE}\n")
        add_labels(issue_number, LABELS_TO_ADD_ON_CLOSE)
        close_issue(issue_number)
        closed_issues.append(f"#{issue_number}: {title}")

    print("\n📦 Cleanup Summary")
    print(f"✅ Total issues closed: {len(closed_issues)}")
    for item in closed_issues:
        print(f"🔒 {item}")

if __name__ == "__main__":
    main()
