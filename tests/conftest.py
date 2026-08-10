"""共享 fixture 插件注册。"""

pytest_plugins = (
    "tests.fixtures.users",
    "tests.fixtures.resources",
    "tests.fixtures.lifecycle",
)
