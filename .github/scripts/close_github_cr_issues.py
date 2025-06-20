import os
import re
import unicodedata
import requests
from datetime import datetime
from dateutil.parser import parse as parse_date

# ENVIRONMENT VARIABLES
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("REPO")

if not GITHUB_TOKEN or not REPO or "/" not in REPO:
    raise Exception(f"❌ GITHUB_TOKEN or REPO not set properly. GITHUB_TOKEN={'set' if GITHUB_TOKEN else 'unset'}, REPO={REPO}")

REPO_OWNER, REPO_NAME = REPO.strip().split("/")
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

# CONFIGURATION
REQUIRED_LABEL = "Normal Change Request"
SECONDARY_LABELS = {"Application", "Infrastructure"}
DONE_LABEL = "done"
RESOLUTION_LABEL = "Resolution/Done"
EXPECTED_CHECKLIST_KEYWORDS = {"assessed", "authorized", "scheduled", "implemented", "reviewed"}

def normalize_unicode(text):
    """Strip emoji, accents, and convert to lowercase alphanumerics"""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^\w]", "", text).lower()

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
    for comment in comments:
        body = comment["body"].strip()
        if body.startswith("**") and body.endswith("**"):
            body = body[2:-2]
        lines = body.splitlines()
        normalized = set()
        for line in lines:
            line = line.strip()
            if line.startswith(("✔️", "✓", "- [x]", "* [x]")):
                cleaned = re.sub(r"[✓✔️\*\-\[\]xX:]", "", line).strip().lower()
                normalized.add(cleaned)
        print(f"📋 Found normalized checklist: {normalized}")
        if EXPECTED_CHECKLIST_KEYWORDS.issubset(normalized):
            return True
    return False

def issue_has_project_status_done(issue_node_id):
    query = """
    query($issueId: ID!) {
      node(id: $issueId) {
        ... on Issue {
          projectItems(first: 10) {
            nodes {
              project {
                title
              }
              fieldValues(first: 20) {
                nodes {
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    field {
                      ... on ProjectV2FieldCommon {
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
    response = requests.post(
        "https://api.github.com/graphql",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
        json={"query": query, "variables": {"issueId": issue_node_id}},
    )
    response.raise_for_status()
    data = response.json()
    print("📦 Project field values received")

    for item in data["data"]["node"]["projectItems"]["nodes"]:
        if item["project"]["title"] != "Cloud SRE Team":
            continue
        for field in item["fieldValues"]["nodes"]:
            print("🧪 RAW FIELD DUMP:")
            print(field)
            if field.get("field", {}).get("name") == "Status":
                status_value = field.get("name", "").strip()
                normalized = normalize_unicode(status_value)
                print(f"📝 Found raw status: '{status_value}'")
                print(f"🧹 Normalized status: '{normalized}'")
                if "done" in normalized:
                    print("✅ Matched project status containing 'done'")
                    return True
    return False

def add_labels(issue_number, labels):
    print(f"🏷️ Adding labels to #{issue_number}: {labels}")
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/labels"
    response = requests.post(url, headers=HEADERS, json={"labels": labels})
    response.raise_for_status()

def close_issue(issue_number):
    print(f"🔒 Closing issue #{issue_number}")
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    response = requests.patch(url, headers=HEADERS, json={"state": "closed"})
    response.raise_for_status()

def main():
    issues = get_issues()
    closed_issues = []

    print(f"\n🔍 Found {len(issues)} open issues\n")

    for issue in issues:
        issue_number = issue["number"]
        issue_node_id = issue["node_id"]
        title = issue["title"]
        created_at = parse_date(issue["created_at"])
        labels = {label["name"] for label in issue.get("labels", [])}

        print(f"➡️ #{issue_number}: {title}")
        print(f"   📆 Created on: {created_at.date()}")
        print(f"   🏷️ Labels: {labels}")

        if REQUIRED_LABEL not in labels:
            print(f"⏩ Skipped: Missing '{REQUIRED_LABEL}' label\n")
            continue

        if not (SECONDARY_LABELS & labels):
            print(f"⏩ Skipped: Missing one of {SECONDARY_LABELS}\n")
            continue

        if DONE_LABEL in labels:
            print(f"⏩ Skipped: Already has '{DONE_LABEL}' label\n")
            continue

        comments = get_issue_comments(issue_number)
        if not has_required_checklist(comments):
            print(f"⏩ Skipped: Checklist not complete\n")
            continue

        if not issue_has_project_status_done(issue_node_id):
            print(f"⏩ Skipped: Project status is not 'Done'\n")
            continue

        labels_to_add = [DONE_LABEL]
        if RESOLUTION_LABEL not in labels:
            labels_to_add.append(RESOLUTION_LABEL)

        add_labels(issue_number, labels_to_add)
        close_issue(issue_number)
        closed_issues.append(f"#{issue_number}: {title}")

    print("\n📦 Cleanup Summary")
    print(f"✅ Total issues closed: {len(closed_issues)}")
    for closed in closed_issues:
        print(f"🔒 {closed}")

if __name__ == "__main__":
    main()
