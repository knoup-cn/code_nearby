"""支持语言的 tree-sitter 配置注册表。

纯数据模块——不包含 tree-sitter 逻辑。所有 tree-sitter 消费者
（chunker、tree_sitter_utils、graph）都从这里读取语言定义。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LanguageConfig:
    """一门编程语言的不可变配置。

    所有 tree-sitter 节点类型名称均来自对应语法的 node-types.json。
    """

    # ---- 基础标识 ----
    name: str  # "python", "javascript", "typescript", "go", "rust"
    suffixes: tuple[str, ...]  # (".py",) 或 (".js", ".jsx") 等
    grammar_module: str  # "tree_sitter_python" 等
    grammar_attr: str  # 模块中获取 Language 的函数名（通常为 "language"）

    # ---- tree-sitter 节点类型名 ----
    func_type: str  # 顶层函数节点类型
    class_types: tuple[str, ...]  # 类/结构体/接口节点类型
    decorated_type: str | None  # 装饰器包装节点类型（无则为 None）
    # 类内部的方法节点类型（None 表示与 func_type 相同）
    method_func_types: tuple[str, ...] | None

    # ---- wrapper 节点（export / decorated 等包裹声明体的节点） ----
    wrapper_types: tuple[str, ...]

    # ---- 语言语义约定 ----
    is_private_symbol: Callable[[str], bool]  # 私有判断
    has_async_keyword: bool  # 语言是否支持 async 关键字

    # ---- 元数据 ----
    comment_prefix: str  # "#" 或 "//"

    # ---- import 节点类型 ----
    import_node_types: tuple[str, ...]  # 顶层 import 声明节点类型


# ======================================================================
# 语言定义
# ======================================================================

PYTHON = LanguageConfig(
    name="python",
    suffixes=(".py",),
    grammar_module="tree_sitter_python",
    grammar_attr="language",
    func_type="function_definition",
    class_types=("class_definition",),
    decorated_type="decorated_definition",
    method_func_types=None,
    wrapper_types=("decorated_definition",),
    is_private_symbol=lambda name: name.startswith("_"),
    has_async_keyword=True,
    comment_prefix="#",
    import_node_types=("import_statement", "import_from_statement"),
)

JAVASCRIPT = LanguageConfig(
    name="javascript",
    suffixes=(".js", ".jsx", ".mjs", ".cjs"),
    grammar_module="tree_sitter_javascript",
    grammar_attr="language",
    func_type="function_declaration",
    class_types=("class_declaration",),
    decorated_type=None,
    method_func_types=("method_definition",),
    wrapper_types=("export_statement",),
    is_private_symbol=lambda name: name.startswith("_"),
    has_async_keyword=True,
    comment_prefix="//",
    import_node_types=("import_statement",),
)

TYPESCRIPT = LanguageConfig(
    name="typescript",
    suffixes=(".ts", ".tsx", ".mts", ".cts"),
    grammar_module="tree_sitter_typescript",
    grammar_attr="language_typescript",
    func_type="function_declaration",
    class_types=("class_declaration", "abstract_class_declaration"),
    decorated_type=None,
    method_func_types=("method_definition",),
    wrapper_types=("export_statement",),
    is_private_symbol=lambda name: name.startswith("_"),
    has_async_keyword=True,
    comment_prefix="//",
    import_node_types=("import_statement",),
)

GO = LanguageConfig(
    name="go",
    suffixes=(".go",),
    grammar_module="tree_sitter_go",
    grammar_attr="language",
    func_type="function_declaration",
    class_types=("type_declaration",),
    decorated_type=None,
    method_func_types=("method_declaration",),
    wrapper_types=(),
    is_private_symbol=lambda name: len(name) > 0 and name[0].islower(),
    has_async_keyword=False,
    comment_prefix="//",
    import_node_types=("import_declaration",),
)

RUST = LanguageConfig(
    name="rust",
    suffixes=(".rs",),
    grammar_module="tree_sitter_rust",
    grammar_attr="language",
    func_type="function_item",
    class_types=("struct_item", "enum_item", "impl_item", "trait_item"),
    decorated_type=None,
    method_func_types=None,
    wrapper_types=(),
    is_private_symbol=lambda name: not (len(name) > 0 and name[0].isupper()),
    has_async_keyword=True,
    comment_prefix="//",
    import_node_types=("use_declaration",),
)

JAVA = LanguageConfig(
    name="java",
    suffixes=(".java",),
    grammar_module="tree_sitter_java",
    grammar_attr="language",
    func_type="method_declaration",  # Java 无顶层函数，method/constructor 在类内
    class_types=(
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
    ),
    decorated_type=None,
    method_func_types=("method_declaration", "constructor_declaration"),
    wrapper_types=(),
    is_private_symbol=lambda name: False,  # Java 用修饰符而非命名约定
    has_async_keyword=False,
    comment_prefix="//",
    import_node_types=("import_declaration",),
)

# ======================================================================
# 注册表
# ======================================================================

_CONFIGS: dict[str, LanguageConfig] = {
    "python": PYTHON,
    "javascript": JAVASCRIPT,
    "typescript": TYPESCRIPT,
    "go": GO,
    "rust": RUST,
    "java": JAVA,
}

# 后缀 → 语言名映射，从 _CONFIGS 自动构建
LANGUAGES_BY_SUFFIX: dict[str, str] = {}
for _cfg in _CONFIGS.values():
    for _suf in _cfg.suffixes:
        LANGUAGES_BY_SUFFIX[_suf] = _cfg.name


# ======================================================================
# 公共 API
# ======================================================================


def get_config(language: str) -> LanguageConfig:
    """根据语言名获取配置，未知语言抛出 ValueError。"""
    if language not in _CONFIGS:
        raise ValueError(f"不支持的语言: {language}")
    return _CONFIGS[language]


def detect_language(path: Path) -> str | None:
    """根据文件后缀映射到语言名，不支持则返回 None。"""
    return LANGUAGES_BY_SUFFIX.get(path.suffix)
