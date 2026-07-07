const statusText = document.querySelector("#statusText");
const fileInput = document.querySelector("#fileInput");
const uploadResult = document.querySelector("#uploadResult");
const reindexButton = document.querySelector("#reindexButton");
const crawlButton = document.querySelector("#crawlButton");
const askButton = document.querySelector("#askButton");
const questionInput = document.querySelector("#questionInput");
const questionFileInput = document.querySelector("#questionFileInput");
const attachmentList = document.querySelector("#attachmentList");
const answerView = document.querySelector("#answerView");

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`请求失败：HTTP ${response.status}`);
  }
  return response.json();
}

async function refreshStatus() {
  try {
    const data = await fetchJson("/api/status");
    statusText.textContent = `已入库 ${data.documents} 份文档，${data.chunks} 个片段`;
  } catch (error) {
    statusText.textContent = "后端服务未连接，请先运行 python app.py";
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderInline(value) {
  return escapeHtml(value).replace(/https?:\/\/[^\s<]+/g, (url) => {
    const cleanUrl = url.replace(/[。；;]+$/, "");
    const trailing = url.slice(cleanUrl.length);
    return `<a href="${cleanUrl}" target="_blank" rel="noopener noreferrer">${cleanUrl}</a>${escapeHtml(trailing)}`;
  });
}

function renderAttachmentList() {
  const files = Array.from(questionFileInput.files || []);
  attachmentList.innerHTML = files
    .map((file) => `<span class="attachmentChip">${escapeHtml(file.name)}</span>`)
    .join("");
}

function renderFormattedAnswer(text) {
  const headings = new Set([
    "结论",
    "要点",
    "需要准备",
    "办理步骤",
    "建议步骤",
    "依据",
    "查看文档",
    "建议",
    "时间",
    "注意",
    "校内人员补助标准",
    "住宿费限额",
    "城市间交通标准",
    "特殊情况",
  ]);
  const lines = String(text || "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  let html = "";
  let listOpen = false;

  function closeList() {
    if (listOpen) {
      html += "</ol>";
      listOpen = false;
    }
  }

  for (const line of lines) {
    if (headings.has(line)) {
      closeList();
      html += `<h4>${escapeHtml(line)}</h4>`;
      continue;
    }

    const numbered = line.match(/^(\d+)[.、]\s*(.+)$/);
    if (numbered) {
      if (!listOpen) {
        html += "<ol>";
        listOpen = true;
      }
      html += `<li>${renderInline(numbered[2])}</li>`;
      continue;
    }

    closeList();
    const className = line.startsWith("依据：") ? ' class="basisLine"' : "";
    html += `<p${className}>${renderInline(line)}</p>`;
  }

  closeList();
  return html || "<p>暂无答复。</p>";
}

function renderAnswer(data) {
  const flow = Array.isArray(data.flow) && data.flow.length
    ? `<div class="flowBlock"><h3>建议流程</h3><ol>${data.flow.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></div>`
    : "";

  answerView.innerHTML = `
    <div class="answerBlock">
      <h3>答复 <span class="badge">置信度：${escapeHtml(data.confidence || "未知")}</span></h3>
      <div class="answerContent">${renderFormattedAnswer(data.answer || "")}</div>
    </div>
    ${flow}
  `;
}

fileInput.addEventListener("change", async () => {
  if (!fileInput.files.length) return;
  const form = new FormData();
  for (const file of fileInput.files) {
    form.append("files", file);
  }

  fileInput.disabled = true;
  uploadResult.textContent = "正在上传并入库...";
  try {
    const data = await fetchJson("/api/upload", { method: "POST", body: form });
    uploadResult.textContent = `已保存 ${data.saved.length} 个文件，新增 ${data.ingest.added_chunks} 个知识片段。`;
    if (data.ingest.warnings?.length) {
      uploadResult.textContent += ` 有 ${data.ingest.warnings.length} 条解析提示。`;
    }
    await refreshStatus();
  } catch (error) {
    uploadResult.textContent = error.message || "上传失败，请稍后重试。";
  } finally {
    fileInput.disabled = false;
    fileInput.value = "";
  }
});

reindexButton.addEventListener("click", async () => {
  reindexButton.disabled = true;
  uploadResult.textContent = "正在重新扫描...";
  try {
    const data = await fetchJson("/api/ingest", { method: "POST" });
    uploadResult.textContent = `扫描完成：新增 ${data.added_documents} 份文档、${data.added_chunks} 个片段。`;
    await refreshStatus();
  } catch (error) {
    uploadResult.textContent = error.message || "扫描失败，请稍后重试。";
  } finally {
    reindexButton.disabled = false;
  }
});

crawlButton.addEventListener("click", async () => {
  crawlButton.disabled = true;
  uploadResult.textContent = "正在同步官网制度，可能需要一两分钟...";
  try {
    const data = await fetchJson("/api/crawl-official", { method: "POST" });
    const crawl = data.crawl || {};
    const ingest = data.ingest || {};
    uploadResult.textContent = `同步完成：新增网页 ${crawl.saved_pages || 0} 个，附件 ${crawl.saved_attachments || 0} 个，入库片段 ${ingest.added_chunks || 0} 个。`;
    if (data.errors?.length) {
      uploadResult.textContent += ` 有 ${data.errors.length} 条抓取提示。`;
    }
    await refreshStatus();
  } catch (error) {
    uploadResult.textContent = error.message || "同步失败，请稍后重试。";
  } finally {
    crawlButton.disabled = false;
  }
});

questionFileInput.addEventListener("change", renderAttachmentList);

async function ask() {
  const question = questionInput.value.trim();
  const files = Array.from(questionFileInput.files || []);
  if (!question && !files.length) return;

  askButton.disabled = true;
  askButton.textContent = "检索中";
  answerView.innerHTML = '<div class="emptyState"><strong>正在分析...</strong><span>会优先处理本次问题里的附件，再检索知识库。</span></div>';

  try {
    let data;
    if (files.length) {
      const form = new FormData();
      form.append("question", question);
      for (const file of files) {
        form.append("files", file);
      }
      data = await fetchJson("/api/ask-with-files", { method: "POST", body: form });
    } else {
      data = await fetchJson("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
    }

    if (data.error) {
      throw new Error(data.error);
    }
    renderAnswer(data);
    questionFileInput.value = "";
    renderAttachmentList();
  } catch (error) {
    answerView.innerHTML = `<div class="emptyState"><strong>请求没有完成</strong><span>${escapeHtml(error.message || "请稍后重试。")}</span></div>`;
  } finally {
    askButton.disabled = false;
    askButton.textContent = "发送";
  }
}

askButton.addEventListener("click", ask);
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    ask();
  }
});

refreshStatus();
