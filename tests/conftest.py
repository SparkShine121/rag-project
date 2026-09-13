"""测试全局隔离：默认禁用工作目录 ragdb.toml 发现，防止项目真实配置泄入测试。

需要测试该特性的用例应 monkeypatch.delenv("RAGDB_NO_CWD_CONFIG", raising=False)。
"""

import os

os.environ.setdefault("RAGDB_NO_CWD_CONFIG", "1")
