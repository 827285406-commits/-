const questionInput = document.querySelector("#questionInput");
const askButton = document.querySelector("#askButton");
const sampleButton = document.querySelector("#sampleButton");
const answerView = document.querySelector("#answerView");
const fileInput = document.querySelector("#fileInput");
const uploadResult = document.querySelector("#uploadResult");
const attachmentList = document.querySelector("#attachmentList");

const builtInDocs = [
  {
    title: "研究生培养与学位事务",
    department: "研究生院",
    contact: "研究生培养或学位管理相关老师",
    website: "https://yjs.suda.edu.cn/",
    keywords: ["研究生", "硕士", "博士", "导师", "培养", "开题", "中期", "答辩", "学位", "学籍", "课程"],
    text: "涉及研究生培养、学位、开题、中期、答辩、导师、学籍、课程免修、成绩证明等事项，通常先由所在学院或研究生秘书初审，再按研究生院要求提交材料。办理时应核对适用对象、时间节点、申请表、导师意见、学院审核意见和系统提交记录。",
  },
  {
    title: "本科教学与学籍事务",
    department: "本科生院或教务部门",
    contact: "教务管理相关老师",
    website: "",
    keywords: ["本科", "教务", "选课", "成绩", "考试", "学籍", "转专业", "培养方案", "毕业论文", "推免"],
    text: "涉及本科教学、选课、成绩、考试、学籍、培养方案、毕业论文、推荐优秀应届本科毕业生免试攻读研究生等事项，应优先查看本科生院和所在学院当年通知。学院初审、公示、材料提交和学校复核通常是关键环节。",
  },
  {
    title: "财务报销与经费事务",
    department: "财务处",
    contact: "财务审核或预算管理相关老师",
    website: "",
    keywords: ["财务", "报销", "经费", "发票", "预算", "劳务", "差旅", "付款", "住宿费", "交通费"],
    text: "涉及经费、报销、发票、预算、劳务、差旅、付款等事项，应准备真实完整的票据、审批记录、合同或采购材料，并按经费来源和人员类别核对标准。差旅、设备、劳务等事项可能有不同附件要求，最终以财务处最新口径和系统审核为准。",
  },
  {
    title: "采购与招投标事务",
    department: "采购与招投标管理相关部门",
    contact: "采购管理或招投标相关老师",
    website: "",
    keywords: ["采购", "招标", "招投标", "供应商", "询价", "合同", "仪器设备", "固定资产", "备案"],
    text: "涉及仪器设备、办公物资、服务采购、供应商、询价、合同、固定资产入库等事项，应先确认预算金额、采购方式、合同和验收入库要求。金额较高或纳入集中采购范围的事项，需要按学校采购与招投标管理流程办理。",
  },
  {
    title: "人事与师资事务",
    department: "人力资源处",
    contact: "人事或师资管理相关老师",
    website: "",
    keywords: ["人事", "职称", "聘任", "考核", "人才", "教师", "岗位", "证明", "博士后"],
    text: "涉及教师聘任、职称、考核、人才项目、人事证明、博士后和岗位管理等事项，应关注人力资源处通知，并准备个人材料、单位审核意见和相关证明。",
  },
  {
    title: "学生事务与奖助资助",
    department: "学生工作相关部门",
    contact: "辅导员、学院学生工作老师或学生事务老师",
    website: "",
    keywords: ["学生", "奖学金", "助学金", "资助", "处分", "宿舍", "辅导员", "心理", "毕业生"],
    text: "涉及奖助、资助、处分、学生事务、住宿、心理健康、优秀毕业生等事项，一般由辅导员或学院学生工作条线先行核对资格、材料和公示要求，再提交学校相关部门复核。",
  },
  {
    title: "系统账号与线上流程异常",
    department: "信息化建设与管理相关部门",
    contact: "信息化服务老师",
    website: "",
    keywords: ["账号", "登录", "系统", "校园网", "统一身份认证", "权限", "密码", "信息化", "打不开"],
    text: "涉及统一身份认证、校园网、系统登录、账号权限、线上流程异常、网页打不开等事项，先确认浏览器、网络、账号权限和系统维护通知，再联系信息化服务或业务系统负责部门。",
  },
];

let userDocs = [];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function tokenize(text) {
  const lowered = String(text || "").toLowerCase();
  const latin = lowered.match(/[a-z0-9_]+/g) || [];
  const cjk = lowered.match(/[\u4e00-\u9fff]/g) || [];
  const bigrams = [];
  for (let index = 0; index < lowered.length - 1; index += 1) {
    const pair = lowered.slice(index, index + 2);
    if (/^[\u4e00-\u9fff]{2}$/.test(pair)) bigrams.push(pair);
  }
  return [...latin, ...cjk, ...bigrams].filter(Boolean);
}

function scoreDoc(question, doc) {
  const queryTokens = tokenize(question);
  const haystack = `${doc.title} ${doc.department || ""} ${(doc.keywords || []).join(" ")} ${doc.text}`;
  let score = 0;
  for (const token of queryTokens) {
    if (haystack.includes(token)) score += token.length > 1 ? 2 : 1;
  }
  for (const keyword of doc.keywords || []) {
    if (keyword && question.includes(keyword)) score += 10;
  }
  if (question.includes(doc.department || "__none__")) score += 8;
  return score;
}

function search(question) {
  return [...userDocs, ...builtInDocs]
    .map((doc) => ({ ...doc, score: scoreDoc(question, doc) }))
    .filter((doc) => doc.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

function buildAnswer(question, hits) {
  if (!hits.length) {
    return {
      confidence: "低",
      answer: [
        "结论",
        "暂时没有命中足够明确的制度线索。建议补充关键词，例如事项名称、人员类型、经费来源、办理阶段，或上传相关文本文件后再问。",
        "",
        "建议步骤",
        "1. 先确认事项属于教学、研究生、财务、采购、人事、学生事务还是信息化系统。",
        "2. 查找学校或学院最新通知，注意适用对象、时间节点、材料清单和审批路径。",
        "3. 不能确定时联系所在学院办公室或对应职能部门复核。",
      ].join("\n"),
      sources: [],
    };
  }

  const primary = hits[0];
  const confidence = primary.score >= 24 ? "高" : primary.score >= 12 ? "中" : "低";
  const sourceLines = hits.slice(0, 3).map((hit, index) => `${index + 1}. ${hit.title}（${hit.department || "临时上传资料"}）`);
  const answer = [
    "结论",
    `这个问题最可能归口到：${primary.department || "你本次上传的资料"}。${primary.text}`,
    "",
    "建议步骤",
    "1. 先核对适用对象、办理时间、材料清单和审批层级。",
    "2. 如果涉及系统提交，保留提交截图、审批记录和退回意见。",
    `3. 需要人工确认时，优先联系${primary.contact || "资料对应负责老师或部门"}。`,
    "",
    "依据",
    sourceLines.join("\n"),
  ].join("\n");

  return { confidence, answer, sources: hits };
}

function renderFormattedAnswer(text) {
  const headings = new Set(["结论", "建议步骤", "依据", "要点", "注意"]);
  const lines = String(text || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
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
      html += `<li>${escapeHtml(numbered[2])}</li>`;
      continue;
    }
    closeList();
    html += `<p>${escapeHtml(line)}</p>`;
  }
  closeList();
  return html;
}

function renderResult(result) {
  const sourceHtml = result.sources.length
    ? `<div class="sourceBlock"><h3>命中资料</h3><ol class="sourceList">${result.sources.map((source) => `<li>${escapeHtml(source.title)}<br><span>${escapeHtml(source.department || "临时上传资料")} ${source.website ? `· ${source.website}` : ""}</span></li>`).join("")}</ol></div>`
    : "";

  answerView.innerHTML = `
    <div class="answerBlock">
      <h3>答复 <span class="badge">置信度：${escapeHtml(result.confidence)}</span></h3>
      <div class="answerContent">${renderFormattedAnswer(result.answer)}</div>
    </div>
    ${sourceHtml}
  `;
}

function ask() {
  const question = questionInput.value.trim();
  if (!question) return;
  askButton.disabled = true;
  askButton.textContent = "检索中";
  const result = buildAnswer(question, search(question));
  renderResult(result);
  askButton.disabled = false;
  askButton.textContent = "发送";
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("文件读取失败"));
    reader.readAsText(file, "utf-8");
  });
}

fileInput.addEventListener("change", async () => {
  const files = Array.from(fileInput.files || []);
  if (!files.length) return;
  uploadResult.textContent = "正在读取文件...";
  const loaded = [];
  for (const file of files) {
    try {
      const text = await readFileAsText(file);
      loaded.push({
        title: file.name,
        department: "临时上传资料",
        contact: "资料对应负责老师或部门",
        keywords: tokenize(`${file.name} ${text.slice(0, 400)}`).filter((token) => token.length > 1).slice(0, 120),
        text: text.slice(0, 1200) || "文件已读取，但内容较少。",
      });
    } catch (error) {
      loaded.push({
        title: file.name,
        department: "临时上传资料",
        keywords: [file.name],
        text: "这个文件没有读取成功，请换成 txt、md、csv、json 或 html 文本格式。",
      });
    }
  }
  userDocs = [...loaded, ...userDocs].slice(0, 20);
  attachmentList.innerHTML = userDocs
    .slice(0, 8)
    .map((doc) => `<span class="attachmentChip">${escapeHtml(doc.title)}</span>`)
    .join("");
  uploadResult.textContent = `已加入 ${loaded.length} 个临时文件，本次浏览器会话内可检索。`;
  fileInput.value = "";
});

sampleButton.addEventListener("click", () => {
  const samples = [
    "差旅报销需要准备哪些材料？",
    "研究生开题和中期考核应该找谁办理？",
    "采购仪器设备超过三万元要注意什么？",
    "网页系统打不开应该联系哪个部门？",
  ];
  questionInput.value = samples[Math.floor(Math.random() * samples.length)];
  questionInput.focus();
});

askButton.addEventListener("click", ask);
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) ask();
});
