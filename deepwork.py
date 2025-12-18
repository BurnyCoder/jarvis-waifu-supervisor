import sys
import os
import subprocess
import ctypes
import argparse
import platform
import time
import threading
# --- Configuration ---

# Websites to block (add more if needed)
WEBSITES_TO_BLOCK = [
    "facebook.com",
    "www.facebook.com",
    "linkedin.com",
    "www.linkedin.com",
    "www.facebook.com",
    "facebook.com",
    "www.discord.com",
    "discord.com",
    "reddit.com",
    "www.reddit.com",
    "boards.4chan.org",
    "www.4chan.org",
    "news.ycombinator.com",
    "www.ycombinator.com",
    "ycombinator.com",
    "www.ycombinator.com",
    "linkedin.com",
    "www.linkedin.com",
    "lesswrong.com",
    "www.lesswrong.com",
    "alignmentforum.org",
    "www.alignmentforum.org",
    "bsky.app",
    "www.bsky.app",
    "www.x.com",
    "x.com",
    "www.twitter.com",
    "www.twittter.com",
    "www.twttr.com",
    "www.twitter.fr",
    "www.twitter.jp",
    "www.twitter.rs",
    "www.twitter.uz",
    "twitter.biz",
    "twitter.dk",
    "twitter.events",
    "twitter.ie",
    "twitter.je",
    "twitter.mobi",
    "twitter.nu",
    "twitter.pro",
    "twitter.su",
    "twitter.vn",
    "twitter.com",
    "*.twitter.com",
    "twitter.gd",
    "twitter.im",
    "twitter.hk",
    "twitter.jp",
    "twitter.ch",
    "twitter.pt",
    "twitter.rs",
    "www.twitter.com.br",
    "twitter.ae",
    "twitter.eus",
    "twitter.hk",
    "ns1.p34.dynect.net",
    "ns2.p34.dynect.net",
    "ns3.p34.dynect.net",
    "ns4.p34.dynect.net",
    "d01-01.ns.twtrdns.net",
    "d01-02.ns.twtrdns.net",
    "a.r06.twtrdns.net",
    "b.r06.twtrdns.net",
    "c.r06.twtrdns.net",
    "d.r06.twtrdns.net",
    "api-34-0-0.twitter.com",
    "api-47-0-0.twitter.com",
    "cheddar.twitter.com",
    "goldenglobes.twitter.com",
    "mx003.twitter.com",
    "pop-api.twitter.com",
    "spring-chicken-an.twitter.com",
    "spruce-goose-ae.twitter.com",
    "takeflight.twitter.com",
    "www2.twitter.com",
    "m.twitter.com",
    "mobile.twitter.com",
    "api.twitter.com",
]

# Applications to block (Executable Name: Full Path)
# !! IMPORTANT !! Update these paths if your installations are different!
# Common locations are used below. Check your system.
# Note: The key (e.g., "Discord") is only used for logging/display.
# The script now uses the *filename* from the path to kill the process.
APP_PATHS = {
    "Discord": os.path.expandvars(r"%LocalAppData%\Discord\Discord.exe"), # Target Discord.exe directly
    # Alternative Discord path if Update.exe doesn't work: find the latest app-X.Y.Z\Discord.exe
    # "DiscordApp": os.path.expandvars(r"%LocalAppData%\Discord\app-X.Y.Z\Discord.exe"), # Replace X.Y.Z
    "Telegram": os.path.expandvars(r"%AppData%\Telegram Desktop\Telegram.exe"),
    # Alternative Telegram Path:
    # "TelegramPF": r"C:\Program Files\Telegram Desktop\Telegram.exe",
    "Steam": r"C:\Program Files (x86)\Steam\Steam.exe",
}

# Hosts file path
HOSTS_FILE_PATH = r"C:\Windows\System32\drivers\etc\hosts"
REDIRECT_IP = "127.0.0.1" # Or "0.0.0.0"
HOSTS_MARKER = "# BLOCKED_BY_SCRIPT" # Marker to identify lines added by this script

# --- Helper Functions ---

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
            sys.exit(0) # Exit the non-admin instance
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
        if block or any(HOSTS_MARKER in line for line in lines): # Flush DNS if blocking or if unblocking previously blocked sites
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
            result = subprocess.run(command, check=False, capture_output=True, text=True, creationflags=creationflags) # check=False because it errors if process not found

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
                     if result.stdout: print(f"  Stdout: {result.stdout.strip()}")
                     if result.stderr: print(f"  Stderr: {result.stderr.strip()}")
                 # else: If it is the specific Discord error, do nothing (silence it)

        except FileNotFoundError:
             print(f"Error: 'taskkill' command not found. Is it in your system's PATH?")
        except Exception as e:
            print(f"An unexpected error occurred while trying to kill {executable_name}: {e}")

# --- Helper Functions for Thread Management ---

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

def cancel_break(break_thread, break_cancelled_event, break_end_event):
    """Cancel any active break timer. Returns None (new break_thread value)."""
    if break_thread is not None and break_thread.is_alive():
        print("Cancelling active break...")
        break_cancelled_event.set()
        break_thread.join(timeout=2.0)
    break_cancelled_event.clear()
    break_end_event.clear()
    return None

def stop_killer_thread(killer_thread, stop_event, timeout=5.0):
    """Stop the process killer thread if running. Returns None (new killer_thread value)."""
    if killer_thread is not None and killer_thread.is_alive():
        print("Stopping process killer thread...")
        stop_event.set()
        killer_thread.join(timeout=timeout)
        if killer_thread.is_alive():
            print("Warning: Process killer thread did not stop gracefully.")
    return None

def start_killer_thread(stop_event):
    """Start a new process killer thread. Returns the new thread."""
    print("Starting process killer thread...")
    stop_event.clear()
    killer_thread = threading.Thread(target=process_killer_loop, args=(stop_event,), daemon=True)
    killer_thread.start()
    return killer_thread

# --- Process Killer Thread ---
def process_killer_loop(stop_event):
    """Continuously attempts to kill target processes until stop_event is set."""
    print("Process killer thread started.")
    while not stop_event.is_set():
        kill_target_processes()
        # Check stop_event frequently for responsiveness
        time.sleep(0.1) # Check every 100ms
        if stop_event.wait(timeout=0.9): # Wait for up to 0.9s
            break # Exit loop if event is set during wait
    print("Process killer thread stopped.")

# --- Break Timer Thread ---
def break_timer_thread(minutes, break_end_event, break_cancelled_event):
    """Waits for the specified minutes, then signals that break is over."""
    total_seconds = minutes * 60
    print(f"Break timer started: {minutes} minute(s) ({total_seconds} seconds)")
    
    for remaining in range(total_seconds, 0, -1):
        if break_cancelled_event.is_set():
            print("\nBreak cancelled early.")
            return
        # Print countdown every 60 seconds or at specific milestones
        if remaining % 60 == 0 or remaining == 30 or remaining <= 10:
            mins, secs = divmod(remaining, 60)
            print(f"Break time remaining: {mins:02d}:{secs:02d}")
        time.sleep(1)
    
    if not break_cancelled_event.is_set():
        print("\n*** Break time is over! Returning to block mode... ***")
        break_end_event.set()

# --- Main Execution ---

if __name__ == "__main__":
    # Check OS
    if platform.system() != "Windows":
        print("Error: This script is designed for Windows only.")
        sys.exit(1)

    # Check and request admin privileges
    if not is_admin():
        print("Administrator privileges required. Requesting elevation...")
        run_as_admin() # This will exit the current script if elevation is successful/attempted

    # --- Interactive Mode ---
    current_mode = "on" # Start in 'on' mode
    killer_thread = None
    stop_event = threading.Event()
    break_end_event = threading.Event()
    break_cancelled_event = threading.Event()
    break_thread = None

    print("--- Initializing: Ensuring system is in 'on' mode ---")
    modify_hosts(block=True) # Ensure blocked state initially
    # Start the killer thread immediately for the initial 'on' state
    killer_thread = start_killer_thread(stop_event)

    print("\n--- Deep Work Script Interactive Mode ---")
    print("Commands:")
    print("  on           - Block distractions")
    print("  off          - Unblock distractions (requires confirmation)")
    print("  break <min>  - Take a timed break (e.g., 'break 5' for 5 minutes)")
    print("  exit         - Exit the script")

    try:
        while True:
            # Check if break timer has expired
            if break_end_event.is_set():
                print("\n--- Break ended, re-enabling blocks ---")
                modify_hosts(block=True)
                # Restart the killer thread
                if killer_thread is None or not killer_thread.is_alive():
                    killer_thread = start_killer_thread(stop_event)
                current_mode = "on"
                break_end_event.clear()
                break_thread = None
                print("--- Block ('on' mode) re-activated after break ---")

            try:
                # Add a newline before the prompt for cleaner output
                user_input = input(f"\nCurrent mode: {current_mode}. \nEnter command (on/off/break <min>/exit): \n").strip().lower()
            except EOFError: # Handle Ctrl+Z or pipe closing
                print("\nEOF received, exiting...")
                user_input = "exit"

            if user_input == "on":
                if current_mode == "on":
                    print("Already in 'on' mode.")
                    continue

                # Cancel any active break
                break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)

                print("--- Switching to Block ('on' mode) ---")
                modify_hosts(block=True)
                current_mode = "on"
                # Start the killer thread if it's not running
                if killer_thread is None or not killer_thread.is_alive():
                    killer_thread = start_killer_thread(stop_event)
                print("--- Block ('on' mode) activated ---")

            elif user_input == "off":
                if current_mode == "off":
                    print("Already in 'off' mode.")
                    continue
                print("--- Switching to Unblock ('off' mode) ---")

                # Cancel any active break
                break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)

                # Confirmation prompt
                if not prompt_confirmation("I will not stop cool deepwork session", "'off' switch"):
                    continue

                # Stop the killer thread if it's running
                killer_thread = stop_killer_thread(killer_thread, stop_event)
                modify_hosts(block=False)
                current_mode = "off"
                print("--- Unblock ('off' mode) activated ---")

            elif user_input.startswith("break"):
                # Parse the break command
                parts = user_input.split()
                if len(parts) != 2:
                    print("Usage: break <minutes>  (e.g., 'break 5' for a 5-minute break)")
                    continue
                
                try:
                    break_minutes = int(parts[1])
                    if break_minutes <= 0:
                        print("Break duration must be a positive number of minutes.")
                        continue
                    if break_minutes > 60:
                        print("Warning: Break duration is longer than 60 minutes. Are you sure?")
                        try:
                            confirm = input("Type 'yes' to confirm long break: ").strip().lower()
                            if confirm != 'yes':
                                print("Break cancelled.")
                                continue
                        except EOFError:
                            print("\nBreak cancelled.")
                            continue
                except ValueError:
                    print(f"Invalid duration: '{parts[1]}'. Please enter a number of minutes.")
                    continue

                # Confirmation prompt for break
                if not prompt_confirmation("I will not stop cool deepwork session", "break"):
                    continue

                # If already on break, cancel current break first
                if current_mode == "break":
                    print("Cancelling current break and starting new one...")
                    break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)

                print(f"--- Starting {break_minutes}-minute break ---")

                # Stop the killer thread if running
                killer_thread = stop_killer_thread(killer_thread, stop_event)
                
                # Unblock sites
                modify_hosts(block=False)
                current_mode = "break"
                
                # Start the break timer thread
                break_cancelled_event.clear()
                break_end_event.clear()
                break_thread = threading.Thread(
                    target=break_timer_thread, 
                    args=(break_minutes, break_end_event, break_cancelled_event), 
                    daemon=True
                )
                break_thread.start()
                
                print(f"--- Break mode active for {break_minutes} minute(s) ---")
                print("Sites and apps are temporarily unblocked.")
                print("Type 'on' to end break early, or wait for timer to expire.")

            elif user_input == "exit":
                print("--- Exiting Script ---")

                # Cancel any active break
                break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)

                # Ensure everything is unblocked on exit
                if current_mode == "on" or current_mode == "break":
                    print("Switching to 'off' mode before exiting...")
                    killer_thread = stop_killer_thread(killer_thread, stop_event)
                    modify_hosts(block=False)
                    current_mode = "off" # Update status for final message
                    print("'off' mode restored.")
                print("Exiting.")
                break # Exit the main loop

            else:
                print(f"Invalid command: '{user_input}'. Please use 'on', 'off', 'break <min>', or 'exit'.")

    except KeyboardInterrupt:
        print("\nCtrl+C detected. Exiting gracefully...")
        # Cancel any active break
        break_thread = cancel_break(break_thread, break_cancelled_event, break_end_event)
        # Perform cleanup similar to 'exit' command
        if current_mode == "on" or current_mode == "break":
            print("Switching to 'off' mode before exiting...")
            killer_thread = stop_killer_thread(killer_thread, stop_event, timeout=2.0)
            modify_hosts(block=False)
            print("'off' mode restored.")
        print("Exiting.")
    finally:
        # Final check to ensure thread is stopped if still alive somehow
        if killer_thread is not None and killer_thread.is_alive():
            print("Final check: Stopping lingering process killer thread...")
            stop_event.set()
            # No long join here, as we are force exiting

        print("\nScript finished.")
        # No need for input("Press Enter...") in interactive mode