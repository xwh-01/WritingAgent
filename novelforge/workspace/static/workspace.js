const state = {
    stories: [],
    story: null,
    activeChapter: 1,
    activeJob: null,
    polling: null,
};

const els = {};

document.addEventListener("DOMContentLoaded", async () => {
    bindElements();
    bindEvents();
    await loadStories();
    const initial = window.NOVELFORGE_STORY_ID || state.stories[0]?.id;
    if (initial) {
        await loadStory(initial);
    }
    renderIcons();
});

function bindElements() {
    for (const id of [
        "connectionState", "refreshStoriesBtn", "newStoryForm", "newTitle", "newPremise", "newGenre",
        "storyList", "chapterList", "storyTitle", "storyPremise", "outlineBtn", "writeBtn", "saveBtn",
        "dashboardBtn", "outlineStrip", "chapterTitleInput", "chapterEditor", "reloadStoryBtn",
        "beatsBtn", "reviewBtn", "autoBtn", "reportBtn", "jobStatus", "qualityReport",
        "longformMetrics", "eventLog", "activeChapterMeta",
    ]) {
        els[id] = document.getElementById(id);
    }
}

function bindEvents() {
    els.refreshStoriesBtn.addEventListener("click", loadStories);
    els.reloadStoryBtn.addEventListener("click", () => state.story && loadStory(state.story.id));
    els.newStoryForm.addEventListener("submit", createStory);
    els.outlineBtn.addEventListener("click", generateOutline);
    els.writeBtn.addEventListener("click", writeChapter);
    els.saveBtn.addEventListener("click", saveChapter);
    els.dashboardBtn.addEventListener("click", openDashboard);
    els.beatsBtn.addEventListener("click", generateBeats);
    els.reviewBtn.addEventListener("click", reviewChapter);
    els.autoBtn.addEventListener("click", autoWrite);
    els.reportBtn.addEventListener("click", loadReport);
}

async function loadStories() {
    setStatus("Loading stories");
    const payload = await getJson("/dashboard/stories");
    state.stories = payload.stories || [];
    renderStories();
    setStatus("Ready");
}

async function createStory(event) {
    event.preventDefault();
    const premise = els.newPremise.value.trim();
    if (!premise) return;
    const payload = await postJson("/stories/", {
        title: els.newTitle.value.trim() || premise.slice(0, 24),
        premise,
        genre: els.newGenre.value.trim() || "novel",
        style_guide: "",
    });
    els.newTitle.value = "";
    els.newPremise.value = "";
    await loadStories();
    await loadStory(payload.story.id);
}

async function loadStory(storyId) {
    setStatus("Loading story");
    const payload = await getJson(`/stories/${storyId}/`);
    state.story = payload.story;
    state.activeChapter = pickActiveChapter();
    renderWorkspace();
    setStatus("Ready");
}

function pickActiveChapter() {
    const current = state.story?.current_chapter || 1;
    const outlines = state.story?.outlines || [];
    if (current > 0) return current;
    return outlines[0]?.chapter_index || 1;
}

function renderWorkspace() {
    renderStories();
    renderStoryHeader();
    renderChapters();
    renderOutlines();
    renderEditor();
    renderLongformMetrics();
    renderReport(null);
    renderEvents();
    renderIcons();
}

function renderStories() {
    const activeId = state.story?.id;
    els.storyList.innerHTML = state.stories.length ? state.stories.map(story => `
        <button class="story-item ${story.id === activeId ? "active" : ""}" data-story-id="${escapeHtml(story.id)}">
            <i data-lucide="book-open"></i><span>${escapeHtml(story.title)}</span>
        </button>
    `).join("") : `<div class="project-meta">No stories</div>`;
    els.storyList.querySelectorAll("[data-story-id]").forEach(button => {
        button.addEventListener("click", () => loadStory(button.dataset.storyId));
    });
    renderIcons();
}

function renderStoryHeader() {
    if (!state.story) {
        els.storyTitle.textContent = "未选择故事";
        els.storyPremise.textContent = "";
        return;
    }
    els.storyTitle.textContent = state.story.title;
    els.storyPremise.textContent = state.story.premise;
}

function renderChapters() {
    if (!state.story) {
        els.chapterList.innerHTML = "";
        return;
    }
    const chapterIndexes = collectChapterIndexes();
    els.chapterList.innerHTML = chapterIndexes.map(index => {
        const chapter = getChapter(index);
        const outline = getOutline(index);
        const title = chapter?.title || outline?.title || `第${index}章`;
        return `
            <button class="chapter-item ${index === state.activeChapter ? "active" : ""}" data-chapter="${index}">
                <i data-lucide="file-text"></i><span>${escapeHtml(title)}</span>
            </button>
        `;
    }).join("");
    els.chapterList.querySelectorAll("[data-chapter]").forEach(button => {
        button.addEventListener("click", () => {
            state.activeChapter = Number(button.dataset.chapter);
            renderWorkspace();
        });
    });
}

function renderOutlines() {
    const outlines = state.story?.outlines || [];
    els.outlineStrip.innerHTML = outlines.length ? outlines.map(outline => `
        <button class="outline-item ${outline.chapter_index === state.activeChapter ? "active" : ""}" data-outline="${outline.chapter_index}">
            <i data-lucide="list"></i><span>${escapeHtml(outline.title)}</span>
        </button>
    `).join("") : "";
    els.outlineStrip.querySelectorAll("[data-outline]").forEach(button => {
        button.addEventListener("click", () => {
            state.activeChapter = Number(button.dataset.outline);
            renderWorkspace();
        });
    });
}

function renderEditor() {
    const chapter = getChapter(state.activeChapter);
    const outline = getOutline(state.activeChapter);
    els.chapterTitleInput.value = chapter?.title || outline?.title || `第${state.activeChapter}章`;
    els.chapterEditor.value = chapter?.content || "";
    els.activeChapterMeta.textContent = `Chapter ${state.activeChapter}`;
}

function renderLongformMetrics() {
    const story = state.story;
    if (!story) {
        els.longformMetrics.innerHTML = "";
        return;
    }
    const pending = (story.foreshadowings || []).filter(item => item.status === "pending").length;
    const reports = Object.keys(story.auto_revision_reports || {}).length;
    const summaries = Object.keys(story.chapter_summaries || {}).length;
    const events = (story.causal_events || []).length;
    els.longformMetrics.innerHTML = [
        ["伏笔", pending],
        ["事件", events],
        ["摘要", summaries],
        ["报告", reports],
    ].map(([label, value]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("");
}

function renderEvents() {
    const events = (state.story?.causal_events || []).slice(-8).reverse();
    els.eventLog.innerHTML = events.length ? events.map(event => `
        <div class="event-row">第${event.chapter}章 · ${escapeHtml(event.description)}</div>
    `).join("") : `<div class="event-row">No events</div>`;
}

async function generateOutline() {
    if (!state.story) return;
    const count = Math.max(1, Number(prompt("章节数", "10") || "10"));
    setStatus("Generating outline");
    await postJson(`/stories/${state.story.id}/outline`, { num_chapters: count });
    await loadStory(state.story.id);
}

async function generateBeats() {
    if (!state.story) return;
    setStatus("Generating beats");
    await postJson(`/chapters/${state.activeChapter}/beats?story_id=${state.story.id}`, {});
    await loadStory(state.story.id);
}

async function writeChapter() {
    if (!state.story) return;
    setStatus("Writing chapter");
    await postJson(`/chapters/${state.activeChapter}/write?story_id=${state.story.id}`, {});
    await loadStory(state.story.id);
}

async function saveChapter() {
    if (!state.story) return;
    setStatus("Saving");
    await putJson(`/chapters/${state.activeChapter}/content?story_id=${state.story.id}`, {
        title: els.chapterTitleInput.value.trim() || `第${state.activeChapter}章`,
        content: els.chapterEditor.value,
        status: "draft",
    });
    await loadStory(state.story.id);
}

async function reviewChapter() {
    if (!state.story) return;
    setStatus("Reviewing");
    const payload = await postJson(`/chapters/${state.activeChapter}/review?story_id=${state.story.id}`, {});
    renderReview(payload.report);
    setStatus("Ready");
}

async function autoWrite() {
    if (!state.story) return;
    setStatus("Starting auto-revision");
    const job = await postJson(`/chapters/${state.activeChapter}/auto-write?story_id=${state.story.id}&background=true`, {});
    state.activeJob = job.id;
    pollJob();
}

async function pollJob() {
    clearInterval(state.polling);
    state.polling = setInterval(async () => {
        if (!state.activeJob || !state.story) return;
        const job = await getJson(`/chapters/auto/status?story_id=${state.story.id}&job_id=${state.activeJob}`);
        els.jobStatus.textContent = `${job.status} · round ${job.current_round || 0}`;
        if (["passed", "failed", "stopped", "finished_with_residual_issues"].includes(job.status)) {
            clearInterval(state.polling);
            if (job.result) renderReport(job.result);
            await loadStory(state.story.id);
        }
    }, 1200);
}

async function loadReport() {
    if (!state.story) return;
    const report = await getJson(`/chapters/${state.activeChapter}/report?story_id=${state.story.id}`);
    if (report.error) {
        renderReport(null);
        return;
    }
    renderReport(report);
}

function renderReview(report) {
    const issues = [
        ...(report.logic_issues || []).map(description => ({ severity: "medium", dimension: "逻辑", description })),
        ...(report.character_issues || []).map(description => ({ severity: "medium", dimension: "人设", description })),
        ...(report.pacing_issues || []).map(description => ({ severity: "medium", dimension: "节奏", description })),
    ];
    els.qualityReport.innerHTML = issues.length ? issues.map(issueRow).join("") : `<div class="score-row"><strong>${escapeHtml(report.verdict || "reviewed")}</strong></div>`;
}

function renderReport(report) {
    if (!report) {
        const saved = state.story?.auto_revision_reports?.[state.activeChapter];
        report = saved || null;
    }
    if (!report) {
        els.qualityReport.innerHTML = `<div class="score-row">No report</div>`;
        return;
    }
    const rows = [];
    rows.push(`<div class="score-row"><strong>${Number(report.final_score || 0).toFixed(2)}</strong> · ${report.passed ? "passed" : "not passed"}</div>`);
    for (const round of report.rounds || []) {
        rows.push(`<div class="score-row">Round ${round.round}: <strong>${Number(round.total_score || 0).toFixed(2)}</strong></div>`);
        for (const issue of round.review_report?.issues || []) rows.push(issueRow(issue));
    }
    for (const issue of report.residual_issues || []) rows.push(issueRow(issue));
    els.qualityReport.innerHTML = rows.join("");
}

function issueRow(issue) {
    return `<div class="issue-row ${escapeHtml(issue.severity || "medium")}">[${escapeHtml(issue.dimension || "-")}] ${escapeHtml(issue.description || "")}</div>`;
}

function openDashboard() {
    if (!state.story) return;
    window.open(`/dashboard/?story_id=${state.story.id}`, "_blank");
}

function collectChapterIndexes() {
    const set = new Set();
    for (const outline of state.story?.outlines || []) set.add(outline.chapter_index);
    for (const key of Object.keys(state.story?.chapters || {})) set.add(Number(key));
    if (!set.size) set.add(1);
    return [...set].sort((a, b) => a - b);
}

function getChapter(index) {
    return state.story?.chapters?.[index] || state.story?.chapters?.[String(index)] || null;
}

function getOutline(index) {
    return (state.story?.outlines || []).find(outline => outline.chapter_index === index) || null;
}

async function getJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} ${url}`);
    return response.json();
}

async function postJson(url, body) {
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`${response.status} ${url}`);
    return response.json();
}

async function putJson(url, body) {
    const response = await fetch(url, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`${response.status} ${url}`);
    return response.json();
}

function setStatus(text) {
    els.connectionState.textContent = text;
    els.jobStatus.textContent = text;
}

function renderIcons() {
    if (window.lucide) window.lucide.createIcons();
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
