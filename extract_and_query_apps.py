#!/usr/bin/env python3
"""Compatibility entrypoint for device application extraction."""

from runner.forensiflow.devices.extract_and_query_apps import get_installed_packages, main

__all__ = ["get_installed_packages", "main"]


if __name__ == "__main__":
    main()
