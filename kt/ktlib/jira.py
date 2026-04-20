from datetime import datetime

import requests
from jira import JIRA, Issue, JIRAError
from requests.auth import HTTPBasicAuth


class JiraException(Exception):
    pass


class JiraInstance:
    _jira: JIRA
    _project_key: str
    _api_user: str
    _api_key: str

    def __init__(self, server_url: str, api_user: str, api_key: str, project_key: str):
        try:
            self._jira = JIRA(server=server_url, basic_auth=(api_user, api_key))
        except JIRAError as e:
            raise JiraException(e)

        self._server_url = server_url
        self._project_key = project_key
        self._api_user = api_user
        self._api_key = api_key

    def create_ticket(
        self,
        summary: str,
        description: str,
        issue_type: str,
        priority: str,
        work_category: str,
        product_line: str,
        linux_space: str,
    ) -> Issue:
        issue_dict = {
            "project": {"key": self._project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
            "customfield_10350": {"value": work_category},
            "customfield_10316": [{"value": product_line}],
            "customfield_10398": {"value": linux_space},
        }

        try:
            issue = self._jira.create_issue(fields=issue_dict)
        except JIRAError as e:
            raise JiraException(e)

        return issue

    def get_issue(self, issue_key: str) -> Issue:
        try:
            return self._jira.issue(issue_key)
        except JIRAError as e:
            raise JiraException(e)

    def update_labels(self, issue_key: str, labels: list[str]):
        try:
            issue = self.get_issue(issue_key=issue_key)
            issue.update(fields={"labels": labels})
        except JIRAError as e:
            raise JiraException(e)

    def add_comment(self, issue_key: str, comment: str):
        try:
            self._jira.add_comment(issue_key, comment)
        except JIRAError as e:
            raise JiraException(e)

    def add_worklog(self, issue_key: str, time_spent: str, comment: str, started: datetime):
        try:
            self._jira.add_worklog(issue=issue_key, timeSpent=time_spent, comment=comment, started=started)
        except JIRAError as e:
            raise JiraException(e)

    def transition_issue(self, issue_key: str, transition_name: str):
        try:
            issue = self.get_issue(issue_key=issue_key)
            transition_id = self._get_transition_id(issue=issue, transition_name=transition_name)
            self._jira.transition_issue(issue_key, transition_id)
        except JIRAError as e:
            raise JiraException(e)

    def _get_transition_id(self, issue: Issue, transition_name: str) -> str:
        try:
            transitions = self._jira.transitions(issue)
            for t in transitions:
                if t["name"] == transition_name:
                    return t["id"]
        except JIRAError as e:
            raise JiraException(e)
        raise JiraException(f"Transition '{transition_name}' not found")

    def search_issues(self, jql: str, max_results: int = 1, next_page_token: str = None) -> tuple[list, str]:
        try:
            result = self._jira.enhanced_search_issues(
                jql_str=jql, maxResults=max_results, nextPageToken=next_page_token
            )

            if hasattr(result, "issues"):
                issues = result.issues
            elif isinstance(result, dict) and "issues" in result:
                issues = result["issues"]
            else:
                issues = result

            next_page_token = None
            if hasattr(result, "nextPageToken"):
                next_page_token = result.nextPageToken
            elif isinstance(result, dict) and "nextPageToken" in result:
                next_page_token = result["nextPageToken"]

            return (issues, next_page_token)
        except JIRAError as e:
            raise JiraException(e)

    def _get_user_id(self, email: str) -> str:
        try:
            users = self._jira.search_users(query=email)
            if users:
                return users[0].accountId
        except JIRAError as e:
            raise JiraException(e)

        raise JiraException(f"Could not find user id for {email}")

    def get_user_id(self, email: str) -> str:
        try:
            return self._get_user_id(email=email)
        except JiraException:
            print("Fallback get_user_id")
            return self._get_user_id_fallback(email=email)

    def _get_user_id_fallback(self, email: str) -> str:
        """Fallback: resolve account ID via direct REST API call."""
        auth = HTTPBasicAuth(email, self._api_key)
        headers = {"Accept": "application/json"}
        response = requests.get(
            f"{self._server_url}/rest/api/3/user/assignable/search",
            params={"project": self._project_key, "query": email},
            headers=headers,
            auth=auth,
        )
        if response.status_code != 200:
            raise JiraException(f"Error {response.status_code}: {response.text}")

        users = response.json()
        if not users:
            raise JiraException("No assignable users found for that query.")

        return users[0].get("accountId")

    def _assign_issue_fallback(self, issue_key: str, account_id: str):
        """Fallback: assign via direct REST API call."""
        url = f"{self._server_url}/rest/api/3/issue/{issue_key}/assignee"
        response = self._jira._session.put(url, json={"accountId": account_id})
        if not response.ok:
            raise JiraException(
                f"Failed to assign issue {issue_key} to account {account_id}: {response.status_code} {response.text}"
            )

    def assign_ticket(self, issue_key: str, assignee_email: str = None):
        """Try JIRA lib first, fall back to direct REST API."""

        if assignee_email is None:
            # If there is no assignee given as param, use the default one
            assignee_email = self._api_user

        try:
            assignee_user_id = self.get_user_id(email=assignee_email)
        except JiraException:
            raise JiraException(f"Could not resolve account ID for {assignee_email}")

        try:
            self._jira.assign_issue(issue=issue_key, assignee=assignee_user_id)
        except JIRAError as e:
            print(f"assign_ticket failed ({e}), trying fallback...")
            self._assign_issue_fallback(issue_key=issue_key, account_id=assignee_user_id)

    def get_matching_tickets(self, summary: str) -> list[Issue]:
        escaped_summary = summary.replace('"', '\\"')
        matching_issues = []
        try:
            issues = self._jira.enhanced_search_issues(
                jql_str=f'project={str(self._project_key)} AND summary~"\\"{escaped_summary}\\""',
                maxResults=50,
                nextPageToken=None,
            )
        except JIRAError as e:
            raise JiraException(e)

        if len(issues) > 0:
            for issue in issues:
                if issue.fields.summary == summary:
                    matching_issues.append(issue)

        return matching_issues

    def get_matching_tickets_not_done(self, summary: str) -> list[Issue]:
        matching_issues_not_done = []
        matching_issues = self.get_matching_tickets(summary=summary)

        for issue in matching_issues:
            if issue.fields.statusCategory.name != "Done":
                matching_issues_not_done.append(issue)

        return matching_issues_not_done

    def ticket_in_progress_exists(self, summary: str) -> bool:
        matching_issues = self.get_matching_tickets_not_done(summary=summary)

        return len(matching_issues) > 0
