"""重构方案 6：评估并优化 signature_hash 使用

当前问题：
- analyzer.py 和 chunker.py 都计算 signature_hash
- 没有明确的使用场景说明
- 可能是过度设计（YAGNI）

调研：
1. 查找 signature_hash 的使用位置
2. 确认是否有实际用途
3. 如有用途：保留并文档化
4. 如无用途：移除并简化代码
"""

from __future__ import annotations

import hashlib
from pathlib import Path


# ============================================================
# 当前实现分析
# ============================================================

"""
当前 signature_hash 出现位置：

1. analyzer.py:249-259
   def _compute_signature_hash(signature: str) -> str:
       normalized = signature.strip()
       return hashlib.sha256(normalized.encode()).hexdigest()[:8]

2. analyzer.py:149, 162, 187, 207
   在 _extract_symbols 中计算并添加到 symbol dict

3. chunker.py:113
   content_hash=compute_content_hash(content)
   （注意：这是 content_hash，不是 signature_hash）

4. operations.py (通过 analyzer 间接使用)
   生成的 Markdown frontmatter 包含 signature_hash

使用场景推测：
- 检测函数/类签名是否变更（用于增量更新）
- 比较不同版本的签名差异
- 作为符号的唯一标识符（除了名称之外）
"""


# ============================================================
# 场景 1：确实需要 signature_hash（保留并优化）
# ============================================================


class SignatureHashManager:
    """签名哈希管理器（如果确认需要）。

    用途：
    1. 检测函数签名变更（参数、返回类型变化）
    2. 触发重新索引或文档更新
    3. 作为变更追踪的一部分
    """

    @staticmethod
    def compute(signature: str) -> str:
        """计算签名哈希。

        Args:
            signature: 函数/类签名字符串

        Returns:
            8 字符的十六进制哈希
        """
        normalized = signature.strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:8]

    @staticmethod
    def has_changed(old_hash: str, new_signature: str) -> bool:
        """检测签名是否变更。

        Args:
            old_hash: 旧的签名哈希
            new_signature: 新的签名文本

        Returns:
            True if signature changed
        """
        new_hash = SignatureHashManager.compute(new_signature)
        return old_hash != new_hash


def example_incremental_update_with_hash():
    """演示：使用 signature_hash 实现增量更新。

    场景：只重新分析签名变更的函数，跳过未变更的函数。
    """
    # 伪代码
    old_metadata = {
        "symbols": [
            {"name": "foo", "signature_hash": "a1b2c3d4"},
            {"name": "bar", "signature_hash": "e5f6g7h8"},
        ]
    }

    new_symbols = [
        {"name": "foo", "signature": "def foo(x: int) -> str:"},
        {"name": "bar", "signature": "def bar(y: str) -> int:"},  # 签名变更
    ]

    for new_sym in new_symbols:
        old_sym = next(
            (s for s in old_metadata["symbols"] if s["name"] == new_sym["name"]),
            None
        )

        if old_sym:
            old_hash = old_sym["signature_hash"]
            if not SignatureHashManager.has_changed(old_hash, new_sym["signature"]):
                print(f"Skipping {new_sym['name']} (signature unchanged)")
                continue

        print(f"Re-analyzing {new_sym['name']} (signature changed)")
        # 重新分析并更新文档


# ============================================================
# 场景 2：不需要 signature_hash（移除并简化）
# ============================================================


class MinimalSymbolInfo:
    """简化版符号信息（移除 signature_hash）。

    如果 signature_hash 没有实际用途，直接移除：
    - 减少计算开销
    - 简化数据结构
    - 降低维护成本
    """

    def __init__(self, name: str, signature: str, lineno: int):
        self.name = name
        self.signature = signature  # 保留原始签名即可
        self.lineno = lineno
        # 移除 signature_hash 字段


def simplified_extract_symbols():
    """简化版 _extract_symbols（移除 hash 计算）。"""
    symbols = {
        "functions": [
            {
                "name": "foo",
                "lineno": 10,
                "signature": "def foo(x: int) -> str:",
                # 移除 "signature_hash": "..."
            }
        ]
    }
    return symbols


# ============================================================
# 场景 3：混合方案（延迟计算）
# ============================================================


class LazyHashedSymbol:
    """延迟计算哈希的符号（需要时才计算）。

    如果 signature_hash 偶尔需要但不是每次都用，
    采用延迟计算策略。
    """

    def __init__(self, name: str, signature: str, lineno: int):
        self.name = name
        self.signature = signature
        self.lineno = lineno
        self._hash_cache: str | None = None

    @property
    def signature_hash(self) -> str:
        """延迟计算签名哈希（首次访问时计算）。"""
        if self._hash_cache is None:
            self._hash_cache = SignatureHashManager.compute(self.signature)
        return self._hash_cache


# ============================================================
# 调研方法：追踪 signature_hash 的使用
# ============================================================


def audit_signature_hash_usage():
    """审计 signature_hash 的实际使用情况。

    步骤：
    1. 在 codebase 中搜索 "signature_hash"
    2. 确认每个使用点的目的
    3. 分类：读取 vs 写入 vs 比较
    4. 评估是否可以移除
    """
    usage_locations = [
        # 写入位置
        "analyzer.py:149 - 计算 function signature_hash",
        "analyzer.py:162 - 计算 function signature_hash",
        "analyzer.py:187 - 计算 method signature_hash",
        "analyzer.py:207 - 计算 class signature_hash",

        # 存储位置
        "analyzer.py:425 - 写入 Markdown frontmatter",

        # 读取位置（需要重点查找）
        "??? - 是否有代码读取 frontmatter 中的 signature_hash？",
        "??? - 是否有代码比较 signature_hash 来决定是否更新？",
    ]

    # 如果只有写入，没有读取，说明是 dead code
    has_reader = False  # TODO: 实际检查

    if not has_reader:
        print("⚠️ signature_hash 只写不读，建议移除（YAGNI）")
    else:
        print("✅ signature_hash 有实际用途，建议保留并文档化")


# ============================================================
# 实际检查：搜索 signature_hash 读取位置
# ============================================================


def search_signature_hash_readers(project_root: Path):
    """在代码库中搜索读取 signature_hash 的位置。

    如果只有写入，没有读取，说明是 dead code。
    """
    import subprocess

    # 搜索读取 signature_hash 的代码模式
    patterns = [
        r'signature_hash.*==',   # 比较
        r'\.get\(["\']signature_hash',  # dict 读取
        r'\["signature_hash"\]',  # dict 访问
        r'signature_hash\s*:',    # 类型注解
    ]

    results = []
    for pattern in patterns:
        try:
            output = subprocess.run(
                ["git", "grep", "-n", pattern],
                cwd=project_root,
                capture_output=True,
                text=True,
            )
            if output.stdout:
                results.append(output.stdout)
        except Exception as e:
            print(f"Search error: {e}")

    return "\n".join(results)


# ============================================================
# 推荐方案：基于调研结果
# ============================================================


def recommended_action_plan():
    """基于调研结果的推荐方案。"""
    print("""
# Signature Hash 重构推荐

## 步骤 1：确认使用场景

运行以下命令：
```bash
cd /home/ubuntu/code/knoup/brain
git grep -n "signature_hash" --no-color
```

分析输出：
- 只有写入（analyzer.py 中计算并存储）？ → 移除
- 有读取（其他模块使用）？ → 保留并优化

## 步骤 2a：如果需要保留

理由：
- 用于增量更新（检测签名变更）
- 用于索引失效（chunker 需要知道签名是否变化）

优化措施：
1. 添加文档注释说明用途
2. 在使用点添加示例代码
3. 统一哈希计算逻辑（移到 tree_sitter_utils）

代码示例：
```python
def compute_signature_hash(signature: str) -> str:
    \"\"\"计算签名哈希（用于增量更新检测）。

    用途：
    - 检测函数签名变更（参数、返回类型变化）
    - 触发重新索引
    - 在 RAG 索引中作为 chunk 版本号

    Returns:
        8 字符的 SHA256 哈希前缀
    \"\"\"
    normalized = signature.strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]
```

## 步骤 2b：如果可以移除

理由：
- 只写不读（dead code）
- 功能重复（content_hash 已覆盖）
- 签名文本本身已足够（可以直接比较字符串）

移除步骤：
1. 从 analyzer._extract_symbols 移除 hash 计算
2. 从 Markdown frontmatter 移除 signature_hash 字段
3. 更新测试（移除 signature_hash 断言）
4. 运行全量测试确认无影响

预期收益：
- 减少 SHA256 计算（每个符号节省 ~0.1ms）
- 简化数据结构（减少一个字段）
- 降低维护成本

## 步骤 3：验证

```python
# 测试：移除 signature_hash 后功能正常
def test_without_signature_hash():
    # 分析项目
    result = analyze_project(project_path)
    assert result["success"]

    # 检查生成的 Markdown（不包含 signature_hash）
    kb_file = kb_path / "test_module.md"
    content = kb_file.read_text()
    assert "signature_hash" not in content  # 已移除
    assert "signature:" in content  # 保留原始签名
```
    """)


# ============================================================
# 迁移脚本：批量移除 signature_hash
# ============================================================


def remove_signature_hash_from_markdown(kb_path: Path):
    """批量移除已生成 Markdown 中的 signature_hash 字段。

    如果决定移除 signature_hash，需要清理已生成的文件。
    """
    import re

    count = 0
    for md_file in kb_path.rglob("*.md"):
        if md_file.name.startswith("_"):
            continue

        content = md_file.read_text(encoding="utf-8")

        # 移除 signature_hash 行
        new_content = re.sub(
            r'\n    signature_hash: "[a-f0-9]{8}"\n',
            "\n",
            content
        )

        if new_content != content:
            md_file.write_text(new_content, encoding="utf-8")
            count += 1

    print(f"Removed signature_hash from {count} files")


# ============================================================
# 实际调研脚本
# ============================================================


def main():
    """运行调研脚本。"""
    print("=== Signature Hash 使用情况调研 ===\n")

    project_root = Path("/home/ubuntu/code/knoup/brain")

    print("1. 搜索 signature_hash 使用位置...\n")
    results = search_signature_hash_readers(project_root)

    if results:
        print("找到以下使用位置：")
        print(results)
        print("\n✅ signature_hash 有实际读取，建议保留并优化")
    else:
        print("⚠️ 未找到读取 signature_hash 的代码")
        print("建议：移除 signature_hash（YAGNI 原则）")

    print("\n2. 推荐行动方案：\n")
    recommended_action_plan()


if __name__ == "__main__":
    main()
