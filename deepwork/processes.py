"""Process management for killing distraction applications."""

import os
import subprocess

from .config import APP_PATHS


def kill_target_processes():
    """Find and terminate processes listed in APP_PATHS."""
    killed_any = False
    for app_name, app_path in APP_PATHS.items():
        executable_name = os.path.basename(app_path)
        if not executable_name:
            print(f"Warning: Could not determine executable name for {app_name} from path '{app_path}'. Skipping.")
            continue

        command = ["taskkill", "/F", "/IM", executable_name, "/T"]
        try:
            creationflags = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                command, check=False, capture_output=True, text=True, creationflags=creationflags
            )

            if result.returncode == 0:
                print(f"Successfully sent termination signal to processes matching {executable_name}.")
                killed_any = True
            elif result.returncode == 128 and "not found" in result.stderr.lower():
                pass
            else:
                is_discord_termination_error = (
                    executable_name.lower() == "discord.exe" and
                    result.returncode != 0 and
                    ("could not be terminated" in result.stderr.lower() or
                     "could not be terminated" in result.stdout.lower())
                )

                if not is_discord_termination_error:
                    print(f"Error attempting to kill {executable_name}:")
                    print(f"  Return Code: {result.returncode}")
                    if result.stdout:
                        print(f"  Stdout: {result.stdout.strip()}")
                    if result.stderr:
                        print(f"  Stderr: {result.stderr.strip()}")

        except FileNotFoundError:
            print(f"Error: 'taskkill' command not found. Is it in your system's PATH?")
        except Exception as e:
            print(f"An unexpected error occurred while trying to kill {executable_name}: {e}")

    return killed_any
