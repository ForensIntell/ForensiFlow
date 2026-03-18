"""
Storage Module

Handles saving data (actions, reacts, screenshots, hierarchies).
"""

import json
import logging
import os
from typing import Dict, Any, List, Optional
from pathlib import Path


class StorageModule:
    """Module for storing task execution data."""

    def __init__(self, data_dir: str):
        """
        Initialize storage module.

        Args:
            data_dir: Base directory for storing data
        """
        self.data_dir = data_dir

    def save_screenshot(self, source_path: str, image_index: int) -> str:
        """
        Save screenshot to data directory.

        Args:
            source_path: Path to source screenshot
            image_index: Image index for filename

        Returns:
            Path to saved screenshot
        """
        save_path = os.path.join(self.data_dir, f"{image_index}.jpg")

        if os.path.exists(source_path):
            import shutil
            shutil.copy(source_path, save_path)
            logging.info(f"Screenshot saved to: {save_path}")
        else:
            logging.warning(f"Source screenshot not found: {source_path}")

        return save_path

    def save_hierarchy(
        self,
        hierarchy: str,
        image_index: int,
        device_type: str = "Android"
    ) -> str:
        """
        Save UI hierarchy to data directory.

        Args:
            hierarchy: Hierarchy string (XML or JSON)
            image_index: Image index for filename
            device_type: Device type (Android or Harmony)

        Returns:
            Path to saved hierarchy file
        """
        if device_type == "Android":
            hierarchy_path = os.path.join(self.data_dir, f"{image_index}.xml")
            with open(hierarchy_path, "w", encoding="utf-8") as f:
                f.write(hierarchy)
        else:
            hierarchy_path = os.path.join(self.data_dir, f"{image_index}.json")
            try:
                # Try to parse as JSON
                if isinstance(hierarchy, str):
                    hierarchy_json = json.loads(hierarchy)
                else:
                    hierarchy_json = hierarchy
                with open(hierarchy_path, "w", encoding="utf-8") as f:
                    json.dump(hierarchy_json, f, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, TypeError):
                # Save as plain text if parsing fails
                logging.warning("Failed to parse hierarchy as JSON, saving as plain text")
                with open(hierarchy_path, "w", encoding="utf-8") as f:
                    f.write(str(hierarchy))

        logging.info(f"Hierarchy saved to: {hierarchy_path}")
        return hierarchy_path

    def save_actions(
        self,
        app_name: str,
        old_task: str,
        task: str,
        actions: List[Dict[str, Any]]
    ) -> str:
        """
        Save actions to JSON file.

        Args:
            app_name: Application name
            old_task: Original task description
            task: Current task description
            actions: List of executed actions

        Returns:
            Path to saved actions file
        """
        data = {
            "app_name": app_name,
            "task_type": None,
            "old_task_description": old_task,
            "task_description": task,
            "action_count": len(actions),
            "actions": actions
        }

        actions_path = os.path.join(self.data_dir, "actions.json")
        with open(actions_path, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        logging.info(f"Actions saved to: {actions_path}")
        return actions_path

    def save_reacts(self, reacts: List[Dict[str, Any]]) -> str:
        """
        Save reacts to JSON file.

        Args:
            reacts: List of react data

        Returns:
            Path to saved reacts file
        """
        reacts_path = os.path.join(self.data_dir, "react.json")
        with open(reacts_path, "w", encoding='utf-8') as f:
            json.dump(reacts, f, ensure_ascii=False, indent=4)

        logging.info(f"Reacts saved to: {reacts_path}")
        return reacts_path

    def save_semantic_match_result(
        self,
        step: int,
        target: str,
        match_result: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> str:
        """
        Save semantic matching result details.

        Args:
            step: Step number
            target: Target query text
            match_result: Match result with details
            candidates: All candidate elements with scores

        Returns:
            Path to saved match result file
        """
        import datetime

        data = {
            "step": step,
            "timestamp": datetime.datetime.now().isoformat(),
            "target": target,
            "match_result": match_result,
            "candidates": candidates
        }

        # 为每个步骤创建单独的匹配结果文件
        match_path = os.path.join(self.data_dir, f"semantic_match_step_{step}.json")
        with open(match_path, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        logging.info(f"Semantic match result saved to: {match_path}")
        return match_path

    def create_data_dir(self, base_dir: str) -> str:
        """
        Create a new data directory with auto-incrementing index.

        Args:
            base_dir: Base directory for data storage

        Returns:
            Path to created data directory
        """
        # Find existing directories
        existing_dirs = [
            d for d in os.listdir(base_dir)
            if os.path.isdir(os.path.join(base_dir, d)) and d.isdigit()
        ]

        if existing_dirs:
            data_index = max(int(d) for d in existing_dirs) + 1
        else:
            data_index = 1

        data_dir = os.path.join(base_dir, str(data_index))
        os.makedirs(data_dir)
        logging.info(f"Created data directory: {data_dir}")

        return data_dir

    def get_data_dir(self) -> str:
        """Get current data directory path."""
        return self.data_dir
