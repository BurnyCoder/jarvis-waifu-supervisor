"""
Save Results - Utility for saving text and images to organized folders.

Provides functions to save analysis results (text) and images (screenshots)
with automatic timestamping and folder organization.
"""

import os
from datetime import datetime
from pathlib import Path


# Default output directories
DEFAULT_TEXT_DIR = "results/analysis"
DEFAULT_IMAGE_DIR = "results/screenshots"


def get_timestamp() -> str:
    """Get current timestamp string for filenames."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_directory(path: str | Path) -> Path:
    """Create directory if it doesn't exist."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_text(
    content: str,
    filename: str | None = None,
    directory: str | Path = DEFAULT_TEXT_DIR,
    extension: str = ".txt"
) -> Path:
    """
    Save text content to a file.

    Args:
        content: Text content to save
        filename: Optional filename (without extension). If None, uses timestamp
        directory: Directory to save to
        extension: File extension (default: .txt)

    Returns:
        Path to saved file
    """
    directory = ensure_directory(directory)

    if filename is None:
        filename = f"analysis_{get_timestamp()}"

    if not filename.endswith(extension):
        filename += extension

    filepath = directory / filename
    filepath.write_text(content, encoding="utf-8")

    return filepath


def save_image(
    image_bytes: bytes,
    filename: str | None = None,
    directory: str | Path = DEFAULT_IMAGE_DIR,
    extension: str = ".png"
) -> Path:
    """
    Save image bytes to a file.

    Args:
        image_bytes: Image data as bytes
        filename: Optional filename (without extension). If None, uses timestamp
        directory: Directory to save to
        extension: File extension (default: .png)

    Returns:
        Path to saved file
    """
    directory = ensure_directory(directory)

    if filename is None:
        filename = f"screenshot_{get_timestamp()}"

    if not filename.endswith(extension):
        filename += extension

    filepath = directory / filename
    filepath.write_bytes(image_bytes)

    return filepath


def save_screenshot_with_analysis(
    image_bytes: bytes,
    analysis_text: str,
    base_name: str | None = None,
    image_dir: str | Path = DEFAULT_IMAGE_DIR,
    text_dir: str | Path = DEFAULT_TEXT_DIR
) -> tuple[Path, Path]:
    """
    Save both a screenshot and its analysis with matching names.

    Args:
        image_bytes: Screenshot image data
        analysis_text: Analysis/description text
        base_name: Optional base filename (without extension). If None, uses timestamp
        image_dir: Directory for screenshots
        text_dir: Directory for analysis text

    Returns:
        Tuple of (image_path, text_path)
    """
    if base_name is None:
        base_name = f"capture_{get_timestamp()}"

    image_path = save_image(image_bytes, base_name, image_dir)
    text_path = save_text(analysis_text, base_name, text_dir)

    return image_path, text_path


def list_saved_files(
    directory: str | Path,
    pattern: str = "*"
) -> list[Path]:
    """
    List saved files in a directory.

    Args:
        directory: Directory to list
        pattern: Glob pattern to filter files

    Returns:
        List of file paths, sorted by modification time (newest first)
    """
    directory = Path(directory)
    if not directory.exists():
        return []

    files = list(directory.glob(pattern))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def get_latest_file(
    directory: str | Path,
    pattern: str = "*"
) -> Path | None:
    """
    Get the most recently modified file in a directory.

    Args:
        directory: Directory to search
        pattern: Glob pattern to filter files

    Returns:
        Path to latest file, or None if directory is empty
    """
    files = list_saved_files(directory, pattern)
    return files[0] if files else None
