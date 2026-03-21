const translations = {
  en: {
    appTagline: "AI Company Intelligence",
    appTitle: "Conpany Research Agent",
    languageLabel: "Language",
    switchDeveloper: "Developer View",
    switchUser: "User View",
    heroKicker: "Research Workflow",
    heroTitle: "Get a clean company research summary without reading raw JSON.",
    heroDescription:
      "Enter a company name and the agent will gather market, filing, website, and news signals, then turn them into a readable report.",
    inputLabel: "Company to research",
    submitButton: "Start Research",
    formHint: "Results will appear below in plain language after the research completes.",
    finalSectionKicker: "Final Output",
    finalSectionTitle: "Overall Research Summary",
    companyLabel: "Company",
    limitationsLabel: "Limitations",
    summaryLabel: "Summary",
    keyFindingsLabel: "Key Findings",
    risksLabel: "Risks",
    moduleKicker: "Intermediate Module",
    priceTitle: "Price",
    filingTitle: "Filing",
    websiteTitle: "Website",
    newsTitle: "News",
    highlightsLabel: "Highlights",
    developerKicker: "Developer Console",
    developerTitle: "Inspect the raw API output and compare it with the user-friendly report.",
    developerDescription:
      "This page keeps the JSON-oriented workflow for debugging and validation while the main page presents polished content for end users.",
    developerHint: "The raw response JSON will be shown below for developers.",
    rawKicker: "API Response",
    rawTitle: "Raw JSON Output",
    loading: "Research in progress. The agent is collecting and synthesizing signals, please wait...",
    success: "Research completed successfully.",
    errorPrefix: "Research failed:",
    noData: "No information available.",
    noLimitations: "No explicit limitations were reported.",
    noHighlights: "No highlights were returned for this module.",
    notAvailable: "Not available",
    status_success: "Success",
    status_partial: "Partial",
    status_skipped: "Skipped",
    status_failed: "Failed",
    sentiment_positive: "Positive",
    sentiment_neutral: "Neutral",
    sentiment_negative: "Negative",
  },
  "zh-CN": {
    appTagline: "AI 企业情报",
    appTitle: "企业调研Agent",
    languageLabel: "语言",
    switchDeveloper: "开发者页面",
    switchUser: "用户页面",
    heroKicker: "调研流程",
    heroTitle: "无需阅读原始 JSON，直接获得清晰的企业调研总结。",
    heroDescription: "输入公司名称后，Agent 会汇总股价、财报、官网与新闻信号，并整理成易读的分析结果。",
    inputLabel: "请输入要调研的公司",
    submitButton: "开始调研",
    formHint: "调研完成后，结果会以下方易读内容的形式展示。",
    finalSectionKicker: "最终输出",
    finalSectionTitle: "整体调研结论",
    companyLabel: "公司",
    limitationsLabel: "局限与说明",
    summaryLabel: "总结",
    keyFindingsLabel: "关键发现",
    risksLabel: "风险点",
    moduleKicker: "中间模块",
    priceTitle: "股价",
    filingTitle: "财报/申报",
    websiteTitle: "公司网站",
    newsTitle: "新闻",
    highlightsLabel: "重点信息",
    developerKicker: "开发者控制台",
    developerTitle: "查看原始 API 输出，并与面向用户的展示页面对照。",
    developerDescription: "这个页面保留给开发者调试和校验使用，主页面则向终端用户展示整理后的可读结果。",
    developerHint: "下方会展示原始 JSON 输出，便于开发者查看。",
    rawKicker: "API 响应",
    rawTitle: "原始 JSON 输出",
    loading: "正在执行调研，Agent 正在收集并综合股价、财报、官网和新闻信息，请稍候...",
    success: "调研已完成。",
    errorPrefix: "调研失败：",
    noData: "暂无信息。",
    noLimitations: "当前未报告明显局限。",
    noHighlights: "该模块未返回重点信息。",
    notAvailable: "暂无",
    status_success: "成功",
    status_partial: "部分完成",
    status_skipped: "已跳过",
    status_failed: "失败",
    sentiment_positive: "正向",
    sentiment_neutral: "中性",
    sentiment_negative: "负向",
  },
};

const moduleNames = ["price", "filing", "website", "news"];
const state = {
  language: localStorage.getItem("language") || "en",
  result: null,
};

const body = document.body;
const view = body.dataset.view || "user";
const form = document.getElementById("research-form");
const companyInput = document.getElementById("company-name");
const submitButton = document.getElementById("submit-button");
const statusPanel = document.getElementById("status-panel");
const resultsPanel = document.getElementById("results-panel");
const languageSelect = document.getElementById("language-select");
const rawOutput = document.getElementById("raw-json-output");

function t(key) {
  return translations[state.language]?.[key] || translations.en[key] || key;
}

function prettifyKey(key) {
  const normalized = String(key).replace(/_/g, " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return t("notAvailable");
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (Array.isArray(value)) {
    return value.length ? value.join("; ") : t("notAvailable");
  }
  if (typeof value === "object") {
    const pairs = Object.entries(value)
      .slice(0, 4)
      .map(([key, nestedValue]) => `${prettifyKey(key)}: ${formatValue(nestedValue)}`);
    return pairs.length ? pairs.join(" | ") : t("notAvailable");
  }
  return String(value);
}

function renderTextList(container, items, emptyText) {
  container.innerHTML = "";
  const values = (items || []).filter(Boolean);
  if (!values.length) {
    const placeholder = document.createElement("li");
    placeholder.className = "empty-state";
    placeholder.textContent = emptyText;
    container.appendChild(placeholder);
    return;
  }

  values.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = typeof item === "string" ? item : formatValue(item);
    container.appendChild(li);
  });
}

function renderMetrics(container, metrics) {
  container.innerHTML = "";
  const entries = Object.entries(metrics || {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (!entries.length) {
    const p = document.createElement("p");
    p.className = "empty-state";
    p.textContent = t("noData");
    container.appendChild(p);
    return;
  }

  entries.slice(0, 6).forEach(([key, value]) => {
    const div = document.createElement("div");
    div.className = "metric-item";
    div.innerHTML = `<span class="metric-name">${prettifyKey(key)}</span><span class="metric-value">${formatValue(value)}</span>`;
    container.appendChild(div);
  });
}

function renderUserView(result) {
  document.getElementById("summary-company").textContent = result.company_name || t("notAvailable");
  document.getElementById("summary-text").textContent = result.summary || t("noData");

  const sentimentChip = document.getElementById("summary-sentiment");
  const sentiment = result.overall_sentiment || "neutral";
  sentimentChip.className = `sentiment-chip ${sentiment}`;
  sentimentChip.textContent = t(`sentiment_${sentiment}`);

  renderTextList(document.getElementById("summary-findings"), result.key_findings, t("noData"));
  renderTextList(document.getElementById("summary-risks"), result.risks, t("noData"));
  renderTextList(document.getElementById("summary-limitations"), result.limitations, t("noLimitations"));

  moduleNames.forEach((moduleName) => {
    const moduleCard = document.getElementById(`module-${moduleName}`);
    if (!moduleCard) {
      return;
    }

    const moduleResult = result.module_results?.[moduleName] || {};
    const status = moduleResult.status || "skipped";
    const statusBadge = moduleCard.querySelector("[data-module-status]");
    statusBadge.className = `module-status ${status}`;
    statusBadge.textContent = t(`status_${status}`);

    moduleCard.querySelector("[data-module-summary]").textContent = moduleResult.summary || t("noData");
    renderMetrics(moduleCard.querySelector("[data-module-metrics]"), moduleResult.metrics || {});

    const highlights = [];
    if (Array.isArray(moduleResult.key_points)) {
      highlights.push(...moduleResult.key_points);
    }
    if (Array.isArray(moduleResult.event_timeline)) {
      moduleResult.event_timeline.slice(0, 2).forEach((event) => {
        if (event?.title) {
          highlights.push(`${event.date || t("notAvailable")}: ${event.title}`);
        }
      });
    }
    renderTextList(moduleCard.querySelector("[data-module-keypoints]"), highlights, t("noHighlights"));
  });
}

function renderDeveloperView(result) {
  if (rawOutput) {
    rawOutput.textContent = JSON.stringify(result, null, 2);
  }
}

function renderResult() {
  if (!state.result) {
    return;
  }
  resultsPanel.classList.remove("hidden");
  if (view === "developer") {
    renderDeveloperView(state.result);
  } else {
    renderUserView(state.result);
  }
}

function applyTranslations() {
  document.documentElement.lang = state.language;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.dataset.i18n;
    node.textContent = t(key);
  });

  companyInput.placeholder = state.language === "zh-CN" ? "例如：英伟达 NVIDIA" : "e.g. NVIDIA";
  languageSelect.value = state.language;

  if (view === "developer" && !state.result && rawOutput) {
    rawOutput.textContent = "";
  }

  if (state.result) {
    renderResult();
  }
}

function showStatus(message, type = "info") {
  statusPanel.textContent = message;
  statusPanel.classList.remove("hidden");
  statusPanel.style.borderLeftColor = type === "error" ? "#a12626" : "#2563eb";
}

async function handleSubmit(event) {
  event.preventDefault();
  const companyName = companyInput.value.trim();
  if (!companyName) {
    return;
  }

  submitButton.disabled = true;
  showStatus(t("loading"));
  resultsPanel.classList.add("hidden");

  try {
    const response = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company_name: companyName }),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || response.statusText || "Unknown error");
    }

    state.result = await response.json();
    renderResult();
    showStatus(t("success"));
  } catch (error) {
    state.result = null;
    showStatus(`${t("errorPrefix")} ${error.message}`, "error");
  } finally {
    submitButton.disabled = false;
  }
}

languageSelect.addEventListener("change", (event) => {
  state.language = event.target.value;
  localStorage.setItem("language", state.language);
  applyTranslations();
});

form.addEventListener("submit", handleSubmit);
applyTranslations();
