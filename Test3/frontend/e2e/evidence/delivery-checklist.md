# #18 交付标准复核

核对日期：2026-11-13（Asia/Shanghai）。结论：**离线自动化测试与阶段交付符合要求；团队集成后的最终浏览器验收尚待完成，不能关闭 Issue。**

| Issue 要求 | 核对证据 | 结论 |
|---|---|---|
| 新增浏览器 runner 前先说明方案 | [开工评论](https://github.com/WaterProMax/HexaGraph/issues/18#issuecomment-6846715908) | 已完成 |
| 独立测试目录、最少配置 | `frontend/e2e/`、两个 Playwright 配置及 package/lockfile | 已完成 |
| 创建项目并启动 | `creates a project...`，断言项目名、想法请求体及导航后关卡 | 已覆盖 |
| 确认关卡 | `approves the pending gate...`，断言关卡 ID、approve、裁决理由、阶段变化 | 已覆盖 |
| 暂停/继续 | `pauses and resumes...`，断言两条路径、暂停状态和按钮恢复 | 已覆盖 |
| 终止二次确认 | mock 取消零请求、确认 `confirm:true`、状态和按钮禁用；真实集成另查取消后的服务器状态 | 已覆盖 |
| 接口失败提示 | 项目/运行创建 503、关卡 503 与重试恢复、关卡 409 保持当前阶段 | 已覆盖 |
| 不放宽产品行为 | 验收未通过时空/纯空格理由不能批准；有理由才发请求 | 已加固 |
| 不破坏现有单测和构建 | `npm test`、`npm run build`、测试类型检查，见验证记录 | 已验证 |
| 默认离线、不依赖密钥/付费模型 | mock HTTP 拦截；集成 server 强制 scripted + 临时数据目录 | 已满足 |
| 脱敏截图或 trace、命令、复现 | README、真实截图、每例 trace、验证记录中的失败 node id | 已提供 |
| 向 teamwork-001 提 PR 并回贴 | [PR #22](https://github.com/WaterProMax/HexaGraph/pull/22)、[交付评论](https://github.com/WaterProMax/HexaGraph/issues/18#issuecomment-6848030272) | 已完成 |
| 业务缺陷交回对应负责人 | [#16 基线失败记录](https://github.com/WaterProMax/HexaGraph/issues/16#issuecomment-6848032445) | 已记录，根因待定位 |
| 团队集成后完整浏览器验收 | 当前 `teamwork-001` 仍为 `efdd6eb`；#16 仍 Open，无集成完成的新证据 | **待完成** |

## 本轮优化

- mock 与 integration 分别保存报告、截图和 trace；切换运行模式不再覆盖上一模式的证据。
- 新增 409 冲突、验收失败批准理由边界；503 后在同一页面恢复批准，无需刷新。
- 真实集成取消终止后查真实服务状态并断言零终止请求，确认后检查唯一请求带 `confirm:true`。

## 最终验收剩余动作

待 #14/#15/#16 的团队离线集成有明确版本后，fetch 并核对代码变化，在集成版本复跑浏览器套件，补对应变化所需场景并更新证据。出现业务失败时给出最小复现交回负责人，修复后再测。当前首关及运行控制的真实集成结果，不能代替该最终验收。无需为此调用付费模型。

已有后端基线 10 项失败仍按上次实测列示；本轮仅优化前端测试，没有再次把同一后端基线跑一遍，也没有把失败标成通过。
