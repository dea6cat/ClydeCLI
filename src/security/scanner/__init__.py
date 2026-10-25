# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""In-house security scanner replacing SkillSpector.

Pure-Python, stdlib-only static scanner for skills, plugins, and MCP servers.
Ports rule tables from SkillSpector v2.12.0 (Apache-2.0 licensed).
"""

from __future__ import annotations

from src.security.scanner.engine import scan
from src.security.scanner.rules import (
    RULE_ID_TO_CATEGORY,
    RULE_ID_TO_EXPLANATION,
    RULE_ID_TO_SEVERITY,
)

__all__ = [
    "scan",
    "RULE_ID_TO_CATEGORY",
    "RULE_ID_TO_EXPLANATION",
    "RULE_ID_TO_SEVERITY",
]
