"""Utility functions for the Deep Work script."""

import sys
import os
import ctypes
import subprocess


def is_admin():
    """Check if the script is running with administrative privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin():
    """Re-run the script with administrative privileges."""
    if sys.platform == 'win32':
        script = os.path.abspath(sys.argv[0])
        params = ' '.join([script] + sys.argv[1:])
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            sys.exit(0)  # Exit the non-admin instance
        except Exception as e:
            print(f"Error requesting admin privileges: {e}")
            sys.exit(1)
    else:
        print("This script requires Windows and administrator privileges.")
        sys.exit(1)


def flush_dns():
    """Flush the DNS cache."""
    try:
        print("Flushing DNS cache...")
        subprocess.run(["ipconfig", "/flushdns"], check=True, capture_output=True, text=True)
        print("DNS cache flushed successfully.")
    except FileNotFoundError:
        print("Error: 'ipconfig' command not found. Is it in your system's PATH?")
    except subprocess.CalledProcessError as e:
        print(f"Error flushing DNS cache: {e}")
        print(f"Stderr: {e.stderr}")
    except Exception as e:
        print(f"An unexpected error occurred during DNS flush: {e}")


def prompt_confirmation(phrase, action_name):
    """Prompt user to type a confirmation phrase. Returns True if confirmed, False otherwise."""
    try:
        confirm_input = input(f"Please type the following phrase exactly to confirm: '{phrase}'\nEnter phrase: ")
    except EOFError:
        print(f"\nEOF received during confirmation, cancelling {action_name}.")
        return False

    if confirm_input.strip() != phrase:
        print(f"Confirmation failed. {action_name.capitalize()} cancelled.")
        return False
    return True
