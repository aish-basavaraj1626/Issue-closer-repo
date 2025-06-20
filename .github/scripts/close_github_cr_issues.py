import os
import json
import requests
import unicodedata
import re
from datetime import datetime, timezone
from dateutil.parser import parse as parse_date

# Env Variables
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("REPO")
CHECK_PROJECT_STATUS = os.getenv("CHECK_PROJECT_STATUS", "false").lower() == "true"

if not GITHUB_TOKEN or not REPO or "/" not in REPO:
    raise Exception("❌ GITHUB_TOKEN or REPO not set or invalid format.")

REPO_OWNER, REPO_NAME = REPO.strip().split("/")
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

# Constants
REQUIRED_PRIMARY_LABEL = "Normal Change Request"
REQUIRED_SECONDARY_LABELS = {"Application", "Infrastructure"}
LABELS_TO_ADD_ON_CLOSE = "Resolution/Done"
REQUIRED_CHECKLIST = {
    "assessed", "authorized", "scheduled", "implemented", "reviewed"
}

def normalize(text):
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s]", "", text)
    return text.lower().strip()

def get_issues():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues"
    params = {"state": "open", "per_page": 100}
    response = requests.get(url, headers=HEADERS, params=params)
    response.raise_for_status()
    return response.json()

def get_issue_comments(issue_number):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()

def has_required_checklist(comments):
    found = set()
    for comment in comments:
        body = comment["body"]
        if body.startswith("**") and body.endswith("**"):
            body = body[2:-2]
        lines = body.splitlines()
        for line in lines:
            line = line.strip()
            if line.startswith(("✔️", "✓", "- [x]", "* [x]")):
                clean = normalize(line)
                for item in REQUIRED_CHECKLIST:
                    if item in clean:
                        found.add(item)
    print(f"📋 Found normalized checklist: {found}")
    return REQUIRED_CHECKLIST.issubset(found)

def issue_has_project_status_done(issue_node_id):
    query = """
    query($id: ID!) {
      node(id: $id) {
        ... on Issue {
          projectItems(first: 10) {
            nodes {
              fieldValues(first: 10) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    field {
                      ... on ProjectV2SingleSelectField {
                        name
                      }
                    }
                    name
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    url = "https://api.github.com/graphql"
    payload = {"query": query, "variables": {"id": issue_node_id}}
    headers = {**HEADERS, "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    print("📦 Project field values received")
    try:
        nodes = data["data"]["node"]["projectItems"]["nodes"]
        for project in nodes:
            for field in project["fieldValues"]["nodes"]:
                if field.get("name", "").lower().strip() == "done":
                    return True
    except Exception as e:
        print(f"⚠️ Project check failed: {e}")
    return False

def add_labels(issue_number, labels_to_add):
    # Ensure labels_to_add is always a list
    if isinstance(labels_to_add, str):
        labels_to_add = [labels_to_add]

    # Get current labels to avoid duplicates
    url_get = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    response = requests.get(url_get, headers=HEADERS)
    response.raise_for_status()
    existing_labels = {label["name"] for label in response.json().get("labels", [])}

    # Filter out labels already present
    new_labels = [label for label in labels_to_add if label not in existing_labels]

    if not new_labels:
        print(f"ℹ️ Label(s) {labels_to_add} already present on issue #{issue_number}, skipping label addition.")
        return

    print(f"🏷️ Adding labels to #{issue_number}: {new_labels}")
    url_post = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/labels"
    response = requests.post(url_post, headers=HEADERS, json={"labels": new_labels})
    response.raise_for_status()

def close_issue(issue_number):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    print(f"🔒 Closing issue #{issue_number}")
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
            print("⏩ Skipped: Missing 'Normal Change Request' label\n")
            continue

        if not labels & REQUIRED_SECONDARY_LABELS:
            print(f"⏩ Skipped: Missing one of {REQUIRED_SECONDARY_LABELS}\n")
            continue

        if "done" in labels:
            print("⏩ Skipped: Already has 'done' label\n")
            continue

        comments = get_issue_comments(issue_number)
        if not has_required_checklist(comments):
            print("⏩ Skipped: Checklist not complete\n")
            continue

        if CHECK_PROJECT_STATUS:
            issue_node_id = issue["node_id"]
            if not issue_has_project_status_done(issue_node_id):
                print("⏩ Skipped: Project status is not 'Done'\n")
                continue

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
