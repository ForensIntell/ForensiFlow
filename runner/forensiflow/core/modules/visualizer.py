"""
Visualizer Module

Handles visualization of actions (bounding boxes, click points, arrows, etc.)
"""

import cv2
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont
import textwrap


class VisualizerModule:
    """Module for creating visualizations of executed actions."""

    def __init__(self, font_path: str = "msyh.ttf"):
        """
        Initialize visualizer module.

        Args:
            font_path: Path to font file for text rendering
        """
        self.font_path = font_path

    def visualize_action(
        self,
        action_data: Dict[str, Any],
        screenshot_path: str,
        data_dir: str,
        image_index: int
    ) -> Dict[str, str]:
        """
        Create visualization for an action.

        Args:
            action_data: Action data containing type, position, bounds, etc.
            screenshot_path: Path to original screenshot
            data_dir: Directory to save visualizations
            image_index: Image index for naming files

        Returns:
            Dictionary with paths to created visualization files
        """
        action_type = action_data.get("type", "").lower()

        if action_type == "click":
            return self._visualize_click(action_data, screenshot_path, data_dir, image_index)
        elif action_type == "swipe":
            return self._visualize_swipe(action_data, screenshot_path, data_dir, image_index)
        elif action_type in ["input", "wait", "done"]:
            return self._visualize_simple(action_data, screenshot_path, data_dir, image_index)
        else:
            logging.warning(f"No visualization for action type: {action_type}")
            return {}

    def _visualize_click(
        self,
        action_data: Dict[str, Any],
        screenshot_path: str,
        data_dir: str,
        image_index: int
    ) -> Dict[str, str]:
        """
        Create visualization for click action.

        Args:
            action_data: Click action data
            screenshot_path: Path to screenshot
            data_dir: Output directory
            image_index: Image index

        Returns:
            Paths to created visualization files
        """
        result = {}
        position_x = action_data.get("position_x")
        position_y = action_data.get("position_y")
        bounds = action_data.get("bounds")
        method = action_data.get("method", "unknown")

        # Load image
        img = Image.open(screenshot_path)

        # Add text label
        draw = ImageDraw.Draw(img)
        font = self._get_font(40)
        text = f"CLICK [{position_x}, {position_y}] ({method.upper()})"
        text = textwrap.fill(text, width=20)
        text_width, text_height = draw.textbbox((0, 0), text, font=font)[2:]
        draw.text((img.width / 2 - text_width / 2, 0), text, fill="red", font=font)

        # Save highlighted image
        highlighted_path = os.path.join(data_dir, f"{image_index}_highlighted.jpg")
        img.save(highlighted_path)
        result["highlighted"] = highlighted_path

        # Draw bounding box if available
        if bounds:
            draw_bounds = ImageDraw.Draw(img)
            draw_bounds.rectangle(bounds, outline='red', width=5)

            bounds_path = os.path.join(data_dir, f"{image_index}_bounds.jpg")
            img.save(bounds_path)
            result["bounds"] = bounds_path

            # Draw click point using OpenCV
            cv2image = cv2.imread(bounds_path)
            if cv2image is not None:
                cv2.circle(cv2image, (position_x, position_y), 15, (0, 255, 0), -1)
                click_point_path = os.path.join(data_dir, f"{image_index}_click_point.jpg")
                cv2.imwrite(click_point_path, cv2image)
                result["click_point"] = click_point_path

        return result

    def _visualize_swipe(
        self,
        action_data: Dict[str, Any],
        screenshot_path: str,
        data_dir: str,
        image_index: int
    ) -> Dict[str, str]:
        """
        Create visualization for swipe action.

        Args:
            action_data: Swipe action data
            screenshot_path: Path to screenshot
            data_dir: Output directory
            image_index: Image index

        Returns:
            Paths to created visualization files
        """
        try:
            img = cv2.imread(screenshot_path)
            if img is None:
                return {}

            height, width = img.shape[:2]
            direction = action_data.get("direction", "unknown")

            # Calculate arrow positions
            center_x, center_y = width // 2, height // 2
            arrow_length = min(width, height) // 4

            direction_arrows = {
                "up": ((center_x, center_y + arrow_length // 2), (center_x, center_y - arrow_length // 2)),
                "down": ((center_x, center_y - arrow_length // 2), (center_x, center_y + arrow_length // 2)),
                "left": ((center_x + arrow_length // 2, center_y), (center_x - arrow_length // 2, center_y)),
                "right": ((center_x - arrow_length // 2, center_y), (center_x + arrow_length // 2, center_y)),
            }

            if direction not in direction_arrows:
                logging.warning(f"Unknown swipe direction: {direction}")
                return {}

            start_point, end_point = direction_arrows[direction]

            # Draw arrow
            cv2.arrowedLine(img, start_point, end_point, (255, 0, 0), 8, tipLength=0.3)

            # Add text
            text = f"SWIPE {direction.upper()}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            text_size = cv2.getTextSize(text, font, 1.5, 3)[0]
            text_x = (width - text_size[0]) // 2
            text_y = 50
            cv2.putText(img, text, (text_x, text_y), font, 1.5, (255, 0, 0), 3)

            # Save visualization
            swipe_path = os.path.join(data_dir, f"{image_index}_swipe.jpg")
            cv2.imwrite(swipe_path, img)

            return {"swipe": swipe_path}

        except Exception as e:
            logging.warning(f"Failed to create swipe visualization: {e}")
            return {}

    def _visualize_simple(
        self,
        action_data: Dict[str, Any],
        screenshot_path: str,
        data_dir: str,
        image_index: int
    ) -> Dict[str, str]:
        """
        Create simple visualization for non-interactive actions.

        Args:
            action_data: Action data
            screenshot_path: Path to screenshot
            data_dir: Output directory
            image_index: Image index

        Returns:
            Paths to created visualization files
        """
        action_type = action_data.get("type", "").upper()

        # Copy screenshot with label
        img = Image.open(screenshot_path)
        draw = ImageDraw.Draw(img)
        font = self._get_font(40)

        text = f"{action_type} ACTION"
        text_width, text_height = draw.textbbox((0, 0), text, font=font)[2:]
        draw.text((img.width / 2 - text_width / 2, 0), text, fill="blue", font=font)

        result_path = os.path.join(data_dir, f"{image_index}_{action_type.lower()}.jpg")
        img.save(result_path)

        return {"simple": result_path}

    def _get_font(self, size: int):
        """Get font for text rendering."""
        try:
            return ImageFont.truetype(self.font_path, size)
        except Exception:
            return ImageFont.load_default()
