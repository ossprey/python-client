import requests
import os
import logging

from typing import Iterable, Dict

from cyclonedx.model.vulnerability import Property
from github import Github

from scan.sbom import dict_to_sbom

logger = logging.getLogger(__name__)

def print_gh_action_errors(sbom_dict, package_path, post_to_github=False):
    """
    Print the errors in a format that can be consumed by GitHub Actions
    """
    details = None
    if post_to_github:
        details = create_github_details()

    sbom = dict_to_sbom(sbom_dict)

    if sbom.vulnerabilities is None or len(sbom.vulnerabilities) == 0:
        print("No vulnerabilities found")
        print("::set-output name=has_vulnerabilities::false")
        return True
    else:
        print("::set-output name=has_vulnerabilities::true")
        for vuln in sbom.vulnerabilities:
            properties = properties_to_dict(vuln.properties)
            component = properties["component"]
            version = properties["version"]
            file, line = get_component_reference(component, package_path)
            message = f"WARNING: {component}:{version} contains malware. Remediate this immediately"
            print("Error: " + message)
            print(f"::error file={file},line={line}::{message}")
            with open(os.getenv('GITHUB_OUTPUT'), 'a') as gh_output:
                gh_output.write(f"error={message}\n")

            if post_to_github and details.is_pull_request:
                post_comments_to_pull_request(details.token, details.repo, details.pull_number, details.commit_sha, message, file, line)
                post_comment_to_github_summary(details.token, details.repo, details.pull_number, message)

        return False


def get_component_reference(component, package_path):
    """
    Search through the files in the package until a requirements.txt or setup.py file
    that references the component name is found.

    Args:
        component (str): The name of the component to search for.
        package_path (str): The path to the package directory to search within.

    Returns:
        tuple: A tuple containing the file path and line number where the component is found.
               If the component is not found, returns (None, None).
    """
    files_to_check = ['requirements.txt', 'setup.py']

    for root, _, files in os.walk(package_path):
        for file in files:
            if file in files_to_check:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r') as f:
                        for line_num, line in enumerate(f, start=1):
                            if component in line:
                                return file_path, line_num
                except Exception as e:
                    print(f"Error reading file {file_path}: {e}")

    # If component not found
    return None, None


def properties_to_dict(properties: Iterable[Property]) -> Dict[str, str]:
    """
    Convert properties to a dictionary
    """
    ret = {}
    for prop in properties:
        ret[prop.name] = prop.value
    return ret


class GitHubDetails:
    def __init__(self, token, repo, pull_number, commit_sha, is_pull_request):
        self.token = token
        self.repo = repo
        self.pull_number = pull_number
        self.commit_sha = commit_sha
        self.is_pull_request = is_pull_request


def create_github_details():

    token = os.getenv('GITHUB_TOKEN')
    repo = os.getenv('GITHUB_REPOSITORY')
    event_name = os.getenv('GITHUB_EVENT_NAME')
    pull_number = os.getenv('GITHUB_REF').split('/')[-2]
    is_pull_request = False
    commit_sha = None

    # Validate if this is a pull request or a push to a branch
    if event_name == 'pull_request':
        is_pull_request = True

        # If the pull number is a number, it is a pull request. Otherwise, it is a direct push
        if pull_number.isdigit():
            # Commit Sha
            g = Github(token)
            repo_object = g.get_repo(repo)
            pr = repo_object.get_pull(int(pull_number))
            commit_sha = pr.head.sha
            repo = repo_object.full_name

    return GitHubDetails(token, repo, pull_number, commit_sha, is_pull_request)


def post_comments_to_pull_request(token, repo, pull_number, commit_sha, comment, file_path, line=0):

    data = {
        "body": comment,
        "commit_id": commit_sha,
        "path": file_path,
        "line": line,  # This is the line number in the file, not the diff position
        "side": "RIGHT"  # Comment on the right side (current version of the file)
    }

    # Send the POST request to GitHub API
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    # API URL for pull request comments
    url = f"https://api.github.com/repos/{repo}/pulls/{pull_number}/comments"

    logger.debug(f"Building URL to comments POST: {url}")
    logger.debug(f"Using arguments: {data}")

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 201:
        # print("Comment added successfully.")
        pass
    else:
        print(f"Failed to add comment. Status code: {response.status_code}")
        print(response.json())  # Debugging information


def post_comment_to_github_summary(token, repo, pull_number, comment):
    # GitHub API URL to create a comment on the PR
    # Although we are posting on a Pull-Request we need to use the issues endpoint.
    # This allows us to post a comment that does not include a `commit_id` or `path`.
    url = f"https://api.github.com/repos/{repo}/issues/{pull_number}/comments"

    # Define the comment data
    data = {
        "body": comment
    }

    # Set up the headers with the GitHub token
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Send the POST request to add the comment
    response = requests.post(url, json=data, headers=headers)

    # Check if the comment was successfully added
    if response.status_code == 201:
        print("Comment added successfully.")
    else:
        print(f"Failed to add comment. Status code: {response.status_code}")
        print(response.json())