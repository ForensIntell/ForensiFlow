"""
Screenshot Module

Handles device screenshot capture and image processing.
"""

import base64
import io
import logging
from pathlib import Path
from typing import Dict, Any
from PIL import Image


class ScreenshotModule:
    """Module for capturing and processing device screenshots."""

    def __init__(self, resize_factor: float = 0.5):
        """
        Initialize screenshot module.

        Args:
            resize_factor: Factor to resize the screenshot (default: 0.5)
        """
        self.resize_factor = resize_factor

    def capture(self, device, device_type: str = "Android") -> Dict[str, Any]:
        """
        Capture screenshot from device and return base64 encoded image.

        Args:
            device: Device object (AndroidDevice or HarmonyDevice)
            device_type: Type of device ("Android" or "Harmony")

        Returns:
            Dictionary containing:
                - base64: Base64 encoded image string
                - path: Path to saved screenshot
                - original_size: Original image dimensions (width, height)
                - resized_size: Resized image dimensions (width, height)
        """
        # Determine screenshot path based on device type
        if device_type == "Android":
            screenshot_path = "screenshot-Android.jpg"
        else:
            screenshot_path = "screenshot-Harmony.jpg"

        logging.info(f"Capturing screenshot from {device_type} device...")

        # Capture screenshot
        device.screenshot(screenshot_path)

        logging.info(f"Screenshot saved to: {screenshot_path}")

        # Resize the screenshot to reduce size for processing
        img = Image.open(screenshot_path)
        original_width, original_height = img.size

        resized_img = img.resize(
            (int(img.width * self.resize_factor), int(img.height * self.resize_factor)),
            Image.Resampling.LANCZOS
        )

        # Encode to base64
        buffered = io.BytesIO()
        resized_img.save(buffered, format="JPEG")
        screenshot_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        logging.info(f"  Original size: {original_width}x{original_height}, "
                    f"Resized: {resized_img.width}x{resized_img.height}")

        return {
            "base64": screenshot_base64,
            "path": screenshot_path,
            "original_size": (original_width, original_height),
            "resized_size": (resized_img.width, resized_img.height),
            "image": resized_img  # Keep PIL Image for further processing
        }

    def save_original(self, device, device_type: str, save_path: str) -> str:
        """
        Save original screenshot to specified path.

        Args:
            device: Device object
            device_type: Type of device
            save_path: Path to save the screenshot

        Returns:
            Path to saved screenshot
        """
        if device_type == "Android":
            screenshot_path = "screenshot-Android.jpg"
        else:
            screenshot_path = "screenshot-Harmony.jpg"

        img = Image.open(screenshot_path)
        img.save(save_path)

        logging.info(f"Original screenshot saved to: {save_path}")
        return save_path
