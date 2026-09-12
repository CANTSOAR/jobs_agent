"""Safe, policy-driven browser automation for job applications.

The application browser is intentionally isolated from the scraping browser.  Importing
this package never launches a browser or enables submission.
"""

from .models import ApplicationMode, ApplicationStatus

__all__ = ["ApplicationMode", "ApplicationStatus"]
