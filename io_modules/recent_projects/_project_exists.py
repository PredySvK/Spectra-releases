"""One recent project file: is it still there?"""

import os
from typing import Tuple


def read_project_exists(path: str) -> Tuple[str, bool]:
    return path, os.path.exists(path)
