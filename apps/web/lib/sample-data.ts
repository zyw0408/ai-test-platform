import type { DashboardSnapshot } from "./types";

export const sampleDashboardSnapshot: DashboardSnapshot = {
  projects: [
    {
      id: "proj_demo",
      name: "电商核心链路",
      description: "围绕登录、购物车、下单和支付进行 AI 测试设计与执行。",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    },
  ],
  specs: [
    {
      id: "spec_demo",
      projectId: "proj_demo",
      sourceType: "url",
      title: "Shop API Swagger",
      location: "https://example.com/openapi.json",
      content: "包含登录、购物车、下单三个核心接口。",
      createdAt: new Date().toISOString(),
    },
  ],
  cases: [
    {
      id: "case_api_demo",
      projectId: "proj_demo",
      specId: "spec_demo",
      kind: "api",
      title: "创建订单接口冒烟",
      objective: "验证订单创建主链路可用。",
      steps: [
        "准备有效用户身份令牌。",
        "构造包含商品与地址的下单请求。",
        "断言返回 200 且订单状态为 pending。",
      ],
      assertionHints: ["状态码为 200", "响应体包含 orderId"],
      payload: {
        method: "POST",
        url: "https://example.com/api/orders",
      },
      createdAt: new Date().toISOString(),
    },
    {
      id: "case_ui_demo",
      projectId: "proj_demo",
      specId: "spec_demo",
      kind: "ui",
      title: "Web 下单路径冒烟",
      objective: "验证用户能够从首页完成商品加入购物车和下单。",
      steps: [
        "打开首页并登录。",
        "搜索目标商品并加入购物车。",
        "进入结算页提交订单。",
      ],
      assertionHints: ["出现订单提交成功文案", "生成 trace 产物"],
      payload: {
        startUrl: "https://example.com",
      },
      createdAt: new Date().toISOString(),
    },
  ],
  runs: [
    {
      id: "run_demo",
      projectId: "proj_demo",
      caseId: "case_ui_demo",
      runnerType: "ui",
      status: "running",
      startedAt: new Date().toISOString(),
      finishedAt: null,
      summary: "浏览器已启动，正在执行购物车流程。",
      logs: ["boot ui runner", "open homepage", "await checkout flow"],
      artifactIds: [],
    },
  ],
  artifacts: [],
};
