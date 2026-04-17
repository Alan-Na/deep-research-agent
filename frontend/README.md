# Frontend Contract

这个目录里的当前页面只是一个参考实现。  
如果你要重写前端，优先依赖下面这几层，而不是直接复用 `App.tsx` 的布局代码。

## Stable Boundary

- `src/lib/contracts.ts`
  - 前端消费后端时用到的核心类型定义。
  - 包括 job、memo、evidence、SSE event 的基础结构。
- `src/lib/api.ts`
  - HTTP client 边界。
  - 只负责调用后端接口，不包含页面状态管理。
- `src/lib/events.ts`
  - SSE 订阅边界。
  - `openInvestmentJobEvents(jobId, handlers)` 会打开 `/investment-jobs/{jobId}/events`。

## Backend Endpoints

- `POST /investment-jobs`
- `GET /investment-jobs`
- `GET /investment-jobs/{job_id}`
- `GET /investment-jobs/{job_id}/events`
- `GET /investment-jobs/{job_id}/evidence?agent=&category=`
- `GET /investment-memos/{memo_id}`
- `GET /health`

## Current UI Notes

- `src/App.tsx` 现在是单文件参考实现，后续完全可以替换。
- 如果你要重写页面，建议保留：
  - query key 语义
  - `contracts.ts` 中的类型命名
  - `api.ts` 和 `events.ts` 作为后端适配层

## Suggested Rewrite Path

1. 保留 `src/lib/contracts.ts`
2. 保留或轻改 `src/lib/api.ts`
3. 保留 `src/lib/events.ts`
4. 重新搭建自己的 page/component/store 结构

这样可以把 UI 重写和后端接口稳定性解耦。
