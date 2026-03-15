"""
Executor Module

Handles execution of actions on the device.
"""

import logging
from typing import Dict, Any, Tuple, Optional


class ExecutorModule:
    """Module for executing actions on device."""

    def __init__(self, device):
        """
        Initialize executor module.

        Args:
            device: Device object (AndroidDevice or HarmonyDevice)
        """
        self.device = device

    def execute(
        self,
        action: str,
        parameters: Dict[str, Any],
        grounding_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute an action on the device.

        Args:
            action: Action type (click, input, swipe, wait, done, etc.)
            parameters: Action parameters
            grounding_result: Result from grounder (for click actions)

        Returns:
            Dictionary containing execution result
        """
        action = action.lower()

        if action == "click":
            return self._execute_click(parameters, grounding_result)
        elif action == "input":
            return self._execute_input(parameters)
        elif action == "swipe":
            return self._execute_swipe(parameters)
        elif action == "wait":
            return self._execute_wait()
        elif action in ["done", "stop", "terminate"]:
            return {"status": "completed", "action": action}
        else:
            raise ValueError(f"Unknown action: {action}")

    def _execute_click(
        self,
        parameters: Dict[str, Any],
        grounding_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute click action.

        Args:
            parameters: Action parameters
            grounding_result: Grounding result with position

        Returns:
            Execution result dictionary
        """
        if not grounding_result:
            raise ValueError("Grounding result required for click action")

        position = grounding_result.get("position")
        if not position:
            raise ValueError("Position not found in grounding result")

        x, y = position
        bounds = grounding_result.get("bounds")
        method = grounding_result.get("method", "unknown")

        logging.info(f"Executing CLICK at [{x}, {y}] via {method}")

        self.device.click(x, y)

        return {
            "type": "click",
            "position_x": x,
            "position_y": y,
            "bounds": bounds,
            "method": method
        }

    def _execute_input(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute input action.

        Args:
            parameters: Should contain 'text' key

        Returns:
            Execution result dictionary
        """
        text = parameters.get("text", "")

        if not text:
            raise ValueError("Text parameter required for input action")

        # Check if input is active
        if hasattr(self.device, 'is_input_active') and not self.device.is_input_active():
            logging.warning("Input field is not active")
            raise RuntimeError("Input field is not active. Please click on an input field first.")

        logging.info(f"Executing INPUT: '{text}'")

        self.device.input(text)

        return {
            "type": "input",
            "text": text
        }

    def _execute_swipe(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute swipe action.

        Args:
            parameters: Should contain 'direction' key

        Returns:
            Execution result dictionary
        """
        direction = parameters.get("direction", "").upper()

        if not direction:
            raise ValueError("Direction parameter required for swipe action")

        # Map UI direction to ADB direction
        # For swipe: UI direction is opposite to ADB direction for up/down
        direction_mapping = {
            "DOWN": "up",     # UI down = ADB up
            "UP": "down",     # UI up = ADB down
            "LEFT": "left",   # Same direction
            "RIGHT": "right"  # Same direction
        }

        if direction not in direction_mapping:
            raise ValueError(f"Unknown swipe direction: {direction}")

        adb_direction = direction_mapping[direction]

        logging.info(f"Executing SWIPE: {direction} (ADB: {adb_direction})")

        self.device.swipe(adb_direction, 0.6)

        return {
            "type": "swipe",
            "direction": direction.lower(),
            "adb_direction": adb_direction
        }

    def _execute_wait(self) -> Dict[str, Any]:
        """
        Execute wait action.

        Returns:
            Execution result dictionary
        """
        logging.info("Executing WAIT")

        return {
            "type": "wait"
        }
