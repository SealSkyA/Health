"""权限点定义（内置清单，前后端共享语义）。

权限点两类：
- 页面访问 page.*：控制菜单显示与路由可访问
- 可写操作 op.*.write：控制各业务页的新增/编辑/删除等写操作

admin 为内置超级角色：恒拥有全部权限（后端强制，不落库）。
"""

PERM_GROUPS = [
    {
        "group": "页面访问",
        "items": [
            {"key": "page.report", "label": "检查报告"},
            {"key": "page.med", "label": "用药记录"},
            {"key": "page.files", "label": "文件存储"},
            {"key": "page.tpl", "label": "报告模板"},
            {"key": "page.ai", "label": "AI 配置"},
            {"key": "page.users", "label": "用户管理"},
            {"key": "page.settings", "label": "系统设置"},
            {"key": "page.perms", "label": "权限管理"},
        ],
    },
    {
        "group": "可写操作",
        "items": [
            {"key": "op.report.write", "label": "检查报告-新增/编辑/删除"},
            {"key": "op.med.write", "label": "用药记录-新增/编辑/删除"},
            {"key": "op.files.write", "label": "文件存储-上传/删除"},
            {"key": "op.tpl.write", "label": "报告模板-新增/编辑/删除"},
            {"key": "op.ai.write", "label": "AI 配置-增删改"},
            {"key": "op.settings.write", "label": "系统设置-保存"},
        ],
    },
]

PERM_ALL = [item["key"] for g in PERM_GROUPS for item in g["items"]]
PERM_LABEL = {item["key"]: item["label"] for g in PERM_GROUPS for item in g["items"]}

# viewer 默认权限：五个业务页面可见、无任何写操作、不可见管理页
VIEWER_DEFAULT = [
    p for p in PERM_ALL
    if p.startswith("page.") and p not in ("page.users", "page.settings", "page.perms")
]