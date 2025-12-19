"""Hosts file management for blocking websites."""

import sys

from .config import HOSTS_FILE_PATH, REDIRECT_IP, HOSTS_MARKER, WEBSITES_TO_BLOCK
from .utils import flush_dns


def modify_hosts(block=True):
    """Add or remove entries from the hosts file."""
    print(f"{'Blocking' if block else 'Unblocking'} websites in hosts file...")
    try:
        with open(HOSTS_FILE_PATH, 'r') as f:
            lines = f.readlines()

        # Filter out existing blocked lines first
        filtered_lines = [line for line in lines if HOSTS_MARKER not in line]

        if block:
            # Add new block lines
            for site in WEBSITES_TO_BLOCK:
                filtered_lines.append(f"{REDIRECT_IP}\t{site}\t\t{HOSTS_MARKER}\n")
            action = "blocked"
        else:
            # Just keep the filtered lines (removes the blocks)
            action = "unblocked"

        # Write the modified content back
        with open(HOSTS_FILE_PATH, 'w') as f:
            f.writelines(filtered_lines)

        print(f"Websites {action} successfully.")
        if block or any(HOSTS_MARKER in line for line in lines):
            flush_dns()

    except FileNotFoundError:
        print(f"Error: Hosts file not found at {HOSTS_FILE_PATH}")
        sys.exit(1)
    except PermissionError:
        print(f"Error: Permission denied writing to {HOSTS_FILE_PATH}. Run as Administrator.")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred modifying the hosts file: {e}")
        sys.exit(1)
