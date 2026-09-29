"""GitHub App user sign-in for the GitHub connector.

Repositories are read by the remote GitHub loader
(``docsgpt.parser.remote.github_loader``); this package only signs users in.
"""

from .auth import GitHubAuth

__all__ = ["GitHubAuth"]
