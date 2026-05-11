# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
DeskAgent Workflow Engine
=========================
Python-based workflows for deterministic, reproducible automation.

Usage:
    from workflows import Workflow, step

    class MyWorkflow(Workflow):
        name = "My Workflow"
        allowed_mcp = ["gmail", "datastore"]

        @step
        def first_step(self):
            result = self.tool.gmail_get_email(self.email_id)
            self.email_data = result

        @step
        def second_step(self):
            if self.should_skip:
                return "skip"
"""

from .base import Workflow, step
from . import manager

__all__ = ["Workflow", "step", "manager"]
