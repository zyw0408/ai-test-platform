import { cookies } from "next/headers";

export async function getLang() {
  const cookieStore = await cookies();
  const lang = cookieStore.get("lang")?.value;
  return lang === "en" ? "en" : "zh";
}

export const dictionaries = {
  zh: {
    nav: {
      requirements: "需求分析",
      testCases: "测试用例",
      apiTesting: "接口测试",
      automatedTesting: "自动化测试",
      performance: "性能测试",
      security: "安全测试",
      reports: "测试报告",
      theme: "主题",
      langToggle: "Switch to English",
      mcp: "MCP 节点挂载"
    },
    home: {
      searchPlaceholder: "全局检索...",
      recentTestRuns: "最近需求变更",
      executionMonitor: "用例编排库",
      nextProject: "所有文档",
      projectName: "文档 / 资产名称",
      status: "状态",
      scoreCol: "关联引用数",
      date: "最后编辑"
    }
  },
  en: {
    nav: {
      requirements: "Requirements",
      testCases: "Test Cases",
      apiTesting: "API Testing",
      automatedTesting: "Auto Testing",
      performance: "Performance",
      security: "Security",
      reports: "Reports",
      theme: "Theme",
      langToggle: "切换至中文",
      mcp: "MCP Attached"
    },
    home: {
      searchPlaceholder: "Search...",
      recentTestRuns: "Recent Updates",
      executionMonitor: "Case Library",
      nextProject: "View all",
      projectName: "Asset Name",
      status: "Status",
      scoreCol: "Refs",
      date: "Last Edited"
    }
  }
};
