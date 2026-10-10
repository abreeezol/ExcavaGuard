# 用户上传规范目录

## 默认状态

本目录**默认为空**。

用户未上传规范时，系统**不作任何特殊处理**——不报错、不告警、不提示缺失，
阶段三「规范比对」直接使用默认规范库（`standards/default/`，取自
`C:\Study\bisai\Hai AI Agent\基坑智守项目相关规范`）。

## 怎么用

1. 复制 `user_standard_template.example.json`，重命名为 `*.json`（去掉 `.example`）；
2. 填写 `source_id`、`source_label`（规范/方案全称，会原样输出到判定结果）、
   以及需要覆盖的监测项与规则；
3. 放入本目录即可，下次加载时自动生效。

也可以通过代码上传（推荐，会先做校验）：

```python
from standards_registry import upload_standard
res = upload_standard(payload)   # {"ok": True, "path": ...} 或 {"ok": False, "problems": [...]}
```

## 生效规则

- 用户上传规范的字段**覆盖**默认规范库；
- 未显式给出的字段**继承**默认规范库，不会出现"覆盖即清空"；
- 判定结果中会写明本次实际生效的来源
  （`origin` = `default_library` / `user_uploaded`）与条文出处。

## 命名约定

- `*.json` —— 生效
- `*.example.json` —— 示例/模板，**不加载**

## 强制校验项

上传前会校验，不通过则拒绝写入：

- 必须有 `source_id`、`source_label`、`metrics`
- 每条规则必须有 `rule_id`
- `safety_level` 只允许 `一级` / `二级` / `三级`
- 限值字段必须是数值或 `{min, max}`
- `evidence` 必须给出 `standard`（条文出处），否则结果无法溯源

## 边界

- 只写入本目录，**绝不触碰**默认规范库，也**绝不触碰**任何原始数据目录
- 监测项的键（`metric_key`）必须与默认规范库一致才可覆盖；新增键视为新增监测项
- GB 50497-2019 第 8.0.1 条明确：监测预警值应由基坑工程设计方确定。
  上传的地方规程 / 专项方案应为经审批版本
