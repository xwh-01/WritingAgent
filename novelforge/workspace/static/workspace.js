const state = {
    stories: [],
    story: null,
    activeChapter: 1,
    activeJob: null,
    lastJobEvents: [],
    polling: null,
    directorRunning: false,
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
        "agentRunBtn", "batchBtn", "dashboardBtn", "outlineStrip", "chapterTitleInput", "chapterEditor", "reloadStoryBtn",
        "beatsBtn", "reviewBtn", "autoBtn", "reportBtn", "jobStatus", "qualityReport",
        "longformMetrics", "eventLog", "activeChapterMeta", "agentTrace", "directorInput", "directorRunBtn",
        "directorHints", "contextPreview", "nextActionCard", "nextActionBtn", "agenticRunBtn", "exportDocxBtn",
        "contractEditor", "saveContractBtn", "contractPov", "contractLocation", "contractTime",
        "contractMust", "contractMustNot", "contractGoals", "contractThreads", "contractEnding",
        "contractStyle", "contractNotes", "factLedger", "factCharacter", "factType", "factValue",
        "factFrom", "factUntil", "factNotes", "saveFactBtn",
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
    els.agentRunBtn.addEventListener("click", runDirectorAgent);
    els.batchBtn.addEventListener("click", batchWrite);
    els.saveBtn.addEventListener("click", saveChapter);
    els.dashboardBtn.addEventListener("click", openDashboard);
    if (els.exportDocxBtn) els.exportDocxBtn.addEventListener("click", exportDocx);
    if (els.saveContractBtn) els.saveContractBtn.addEventListener("click", saveChapterContract);
    if (els.saveFactBtn) els.saveFactBtn.addEventListener("click", saveCharacterFact);
    els.beatsBtn.addEventListener("click", generateBeats);
    els.reviewBtn.addEventListener("click", reviewChapter);
    els.autoBtn.addEventListener("click", autoWrite);
    els.reportBtn.addEventListener("click", loadReport);
    if (els.directorRunBtn) els.directorRunBtn.addEventListener("click", runDirectorAgent);
    if (els.agenticRunBtn) els.agenticRunBtn.addEventListener("click", agenticRun);
    if (els.directorInput) {
        els.directorInput.addEventListener("keydown", event => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                event.preventDefault();
                runDirectorAgent();
            }
        });
    }
    document.querySelectorAll("[data-director-prompt]").forEach(button => {
        button.addEventListener("click", () => {
            els.directorInput.value = button.dataset.directorPrompt || "";
            els.directorInput.focus();
        });
    });
    if (els.nextActionBtn) {
        els.nextActionBtn.addEventListener("click", () => runGuideAction(els.nextActionBtn.dataset.guideAction));
    }
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
    renderWorkflow();
    renderGuidedAction();
    renderChapters();
    renderOutlines();
    renderEditor();
    renderLongformMetrics();
    renderReport(null);
    renderDirectorGuide();
    renderAgentTrace();
    renderContextPreview();
    renderEvents();
    updateActionAvailability();
    renderIcons();
}

function renderStories() {
    const activeId = state.story?.id;
    els.storyList.innerHTML = state.stories.length ? state.stories.map(story => `
        <button class="story-item ${story.id === activeId ? "active" : ""}" data-story-id="${escapeHtml(story.id)}">
            <i data-lucide="book-open"></i><span>${escapeHtml(story.title)}</span>
            <span class="story-delete" data-delete-story-id="${escapeHtml(story.id)}" title="Delete">×</span>
        </button>
    `).join("") : `<div class="project-meta">No stories</div>`;
    els.storyList.querySelectorAll("[data-story-id]").forEach(button => {
        button.addEventListener("click", () => loadStory(button.dataset.storyId));
    });
    els.storyList.querySelectorAll("[data-delete-story-id]").forEach(button => {
        button.addEventListener("click", deleteStory);
    });
    renderIcons();
}

async function deleteStory(event) {
    event.stopPropagation();
    const storyId = event.currentTarget.dataset.deleteStoryId;
    const story = state.stories.find(item => item.id === storyId);
    if (!story) return;
    const ok = confirm(`删除《${story.title}》？这会同时清理相关记忆索引。`);
    if (!ok) return;
    setStatus("Deleting story");
    await deleteJson(`/stories/${storyId}`);
    if (state.story?.id === storyId) {
        state.story = null;
        state.activeChapter = 1;
    }
    await loadStories();
    if (!state.story && state.stories[0]) await loadStory(state.stories[0].id);
    if (!state.stories.length) renderWorkspace();
    setStatus("Ready");
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

function renderWorkflow() {
    const steps = [...document.querySelectorAll("[data-workflow-step]")];
    if (!steps.length) return;
    const outlines = state.story?.outlines || [];
    const chapters = state.story?.chapters || {};
    const hasDraft = Object.values(chapters).some(chapter => chapter?.content);
    const hasTrace = Boolean(latestDirectorRun());
    let active = "setup";
    if (state.story && !outlines.length) active = "outline";
    if (state.story && outlines.length) active = "draft";
    if (hasTrace) active = "agent";
    const order = ["setup", "outline", "draft", "agent"];
    const activeIndex = order.indexOf(active);
    for (const step of steps) {
        const index = order.indexOf(step.dataset.workflowStep);
        step.classList.toggle("active", step.dataset.workflowStep === active);
        step.classList.toggle("completed", index >= 0 && index < activeIndex);
        step.classList.toggle("muted", index > activeIndex);
    }
    if (hasDraft && active !== "agent") {
        const draft = steps.find(step => step.dataset.workflowStep === "draft");
        if (draft) draft.classList.add("active");
    }
}

function renderGuidedAction() {
    if (!els.nextActionCard || !els.nextActionBtn) return;
    const guide = getWorkspaceGuide();
    els.nextActionCard.className = `next-action-card ${guide.blocked ? "blocked" : "ready"}`;
    els.nextActionCard.querySelector(".next-title").textContent = guide.title;
    els.nextActionCard.querySelector(".next-meta").innerHTML = `
        <span>${escapeHtml(guide.meta)}</span>
        <span class="next-prereq-title">前置条件</span>
        <div class="next-prereqs">
            ${guide.prerequisites.map(item => `
                <span class="${item.done ? "done" : "todo"}">
                    <i data-lucide="${item.done ? "check" : "circle"}"></i>${escapeHtml(item.label)}
                </span>
            `).join("")}
        </div>
    `;
    els.nextActionBtn.dataset.guideAction = guide.action;
    els.nextActionBtn.disabled = guide.disabled;
    els.nextActionBtn.querySelector("span").textContent = guide.button;
}

function getWorkspaceGuide() {
    const story = state.story;
    const outline = getOutline(state.activeChapter);
    const chapter = getChapter(state.activeChapter);
    const hasStory = Boolean(story);
    const hasOutlines = Boolean(story?.outlines?.length);
    const hasOutline = Boolean(outline);
    const hasBeats = Boolean(chapter?.beats?.length);
    const hasContent = Boolean(chapter?.content?.trim());
    const base = {
        prerequisites: [
            { label: "故事", done: hasStory },
            { label: "大纲", done: hasOutlines },
            { label: "本章细纲", done: hasBeats },
            { label: "正文", done: hasContent },
        ],
        blocked: false,
        disabled: false,
    };
    if (!hasStory) {
        return {
            ...base,
            title: "先创建或选择一个故事",
            meta: "没有故事时，后续大纲、写作和 Agent 都没有落点。",
            button: "填写故事前提",
            action: "focus-premise",
            blocked: true,
        };
    }
    if (!hasOutlines) {
        return {
            ...base,
            title: "生成章节大纲",
            meta: "大纲是后续细纲、正文和长篇记忆的骨架。",
            button: "生成大纲",
            action: "outline",
        };
    }
    if (!hasOutline) {
        return {
            ...base,
            title: "选择一个有大纲的章节",
            meta: "当前章节没有对应大纲，先从上方章节条选择目标章节。",
            button: "查看大纲",
            action: "focus-outline",
            blocked: true,
        };
    }
    if (!hasBeats) {
        return {
            ...base,
            title: `生成第${state.activeChapter}章细纲`,
            meta: "细纲会把章节拆成可执行场景，写出来更稳。",
            button: "生成细纲",
            action: "beats",
        };
    }
    if (!hasContent) {
        return {
            ...base,
            title: `写第${state.activeChapter}章正文`,
            meta: "已有大纲和细纲，可以进入正文写作。",
            button: "写作",
            action: "write",
        };
    }
    return {
        ...base,
        title: "让 Director Agent 做下一轮判断",
        meta: "正文已存在，适合审查、改写、续写或检查伏笔。",
        button: "运行 Agent",
        action: "director",
    };
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
    renderChapterContract();
    renderFactLedger();
}

function renderChapterContract() {
    if (!els.contractEditor) return;
    const contracts = state.story?.chapter_contracts || {};
    const contract = contracts[state.activeChapter] || contracts[String(state.activeChapter)];
    renderCharacterOptions(els.contractPov, contract?.pov_character || "", true);
    els.contractLocation.value = contract?.location || "";
    els.contractTime.value = contract?.time_context || "";
    els.contractMust.value = linesFrom(contract?.must_happen);
    els.contractMustNot.value = linesFrom(contract?.must_not_happen);
    els.contractGoals.value = Object.entries(contract?.character_goals || {})
        .map(([character, goal]) => `${character}: ${goal}`).join("\n");
    els.contractThreads.value = linesFrom(contract?.active_threads);
    els.contractEnding.value = contract?.ending_hook || "";
    els.contractStyle.value = linesFrom(contract?.style_requirements);
    els.contractNotes.value = contract?.notes || "";
    els.contractEditor.value = contract ? JSON.stringify(contract, null, 2) : "";
    els.contractEditor.placeholder = getOutline(state.activeChapter)
        ? "合同尚未生成；点击保存合同会先加载默认合同"
        : "先生成章节大纲";
}

async function saveChapterContract() {
    if (!state.story || !getOutline(state.activeChapter)) {
        setStatus("保存合同前需要先生成本章大纲");
        return;
    }
    try {
        let contract;
        if (!els.contractEditor.value.trim()) {
            contract = await getJson(`/chapters/${state.activeChapter}/contract?story_id=${state.story.id}`);
            els.contractEditor.value = JSON.stringify(contract, null, 2);
            const hasFormInput = [els.contractMust, els.contractMustNot, els.contractEnding, els.contractLocation]
                .some(input => input.value.trim());
            if (!hasFormInput) {
                await loadStory(state.story.id);
                setStatus("默认合同已生成，请检查表单后保存");
                return;
            }
        }
        contract = els.contractEditor.value.trim() ? JSON.parse(els.contractEditor.value) : {};
        contract.chapter_index = state.activeChapter;
        contract.pov_character = els.contractPov.value || null;
        contract.location = els.contractLocation.value.trim();
        contract.time_context = els.contractTime.value.trim();
        contract.must_happen = parseLines(els.contractMust.value);
        contract.must_not_happen = parseLines(els.contractMustNot.value);
        contract.character_goals = parseKeyValueLines(els.contractGoals.value);
        contract.active_threads = parseLines(els.contractThreads.value);
        contract.ending_hook = els.contractEnding.value.trim();
        contract.style_requirements = parseLines(els.contractStyle.value);
        contract.notes = els.contractNotes.value.trim();
        contract.knowledge_boundaries ||= {};
        await putJson(`/chapters/${state.activeChapter}/contract?story_id=${state.story.id}`, contract);
        setStatus(`第${state.activeChapter}章合同已保存`);
        await loadStory(state.story.id);
    } catch (error) {
        setStatus(`合同保存失败: ${error.message}`);
    }
}

function renderFactLedger() {
    if (!els.factLedger) return;
    renderCharacterOptions(els.factCharacter, els.factCharacter.value || "", false);
    els.factFrom.value = els.factFrom.value || String(state.activeChapter);
    const chapter = state.activeChapter;
    const facts = (state.story?.character_facts || []).filter(fact =>
        Number(fact.valid_from_chapter) <= chapter
        && (fact.valid_until_chapter == null || Number(fact.valid_until_chapter) >= chapter)
    );
    if (!facts.length) {
        els.factLedger.innerHTML = '<tr><td colspan="6" class="empty-state">本章暂无人物事实；写作后会自动提取，也可以手动确认。</td></tr>';
        return;
    }
    els.factLedger.innerHTML = facts.map(fact => {
        const character = state.story?.characters?.[fact.character_id];
        const name = character?.name || fact.character_id;
        const source = fact.user_confirmed ? "用户确认" : `第${fact.source_chapter || "?"}章提取`;
        const until = fact.valid_until_chapter == null ? "持续" : `至${fact.valid_until_chapter}章`;
        const action = fact.user_confirmed
            ? `<button class="fact-delete" data-fact-id="${escapeHtml(fact.id)}" title="删除纠正项">×</button>` : "";
        return `<tr><td>${escapeHtml(name)}</td><td>${escapeHtml(fact.fact_type)}</td>`
            + `<td>${escapeHtml(fact.value)}</td><td>${fact.valid_from_chapter}章 / ${until}</td>`
            + `<td>${source}</td><td>${action}</td></tr>`;
    }).join("");
    els.factLedger.querySelectorAll("[data-fact-id]").forEach(button => {
        button.addEventListener("click", () => deleteCharacterFact(button.dataset.factId));
    });
}

async function saveCharacterFact() {
    if (!state.story) {
        setStatus("请先选择故事");
        return;
    }
    try {
        const fact = {
            character_id: els.factCharacter.value,
            fact_type: els.factType.value,
            value: els.factValue.value.trim(),
            valid_from_chapter: Number(els.factFrom.value || state.activeChapter),
            valid_until_chapter: els.factUntil.value ? Number(els.factUntil.value) : null,
            notes: els.factNotes.value.trim(),
            user_confirmed: true,
        };
        if (!fact.character_id || !fact.fact_type || !fact.value) {
            throw new Error("请选择人物、事实类型并填写事实值");
        }
        if (fact.valid_until_chapter != null && fact.valid_until_chapter < fact.valid_from_chapter) {
            throw new Error("失效章节不能早于生效章节");
        }
        await postJson(`/stories/${state.story.id}/facts`, fact);
        els.factValue.value = "";
        els.factUntil.value = "";
        els.factNotes.value = "";
        setStatus("人物事实已确认并保存");
        await loadStory(state.story.id);
    } catch (error) {
        setStatus(`事实保存失败: ${error.message}`);
    }
}

async function deleteCharacterFact(factId) {
    if (!state.story || !factId) return;
    try {
        await deleteJson(`/stories/${state.story.id}/facts/${encodeURIComponent(factId)}`);
        setStatus("人物事实纠正项已删除");
        await loadStory(state.story.id);
    } catch (error) {
        setStatus(`事实删除失败: ${error.message}`);
    }
}

function renderCharacterOptions(select, selected, allowEmpty) {
    if (!select) return;
    const choices = new Map();
    Object.entries(state.story?.characters || {}).forEach(([id, character]) => choices.set(id, character.name || id));
    (state.story?.outlines || []).forEach(outline => {
        if (outline.pov_character) choices.set(outline.pov_character, outline.pov_character);
    });
    const empty = allowEmpty ? '<option value="">未指定</option>' : '<option value="">选择人物</option>';
    select.innerHTML = empty + [...choices.entries()].map(([id, name]) =>
        `<option value="${escapeHtml(id)}">${escapeHtml(name)} (${escapeHtml(id)})</option>`
    ).join("");
    select.value = selected;
}

function parseLines(value) {
    return String(value || "").split(/\r?\n/).map(item => item.trim()).filter(Boolean);
}

function linesFrom(items) {
    return (items || []).join("\n");
}

function parseKeyValueLines(value) {
    const result = {};
    parseLines(value).forEach(line => {
        const index = line.search(/[:：]/);
        if (index > 0) result[line.slice(0, index).trim()] = line.slice(index + 1).trim();
    });
    return result;
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

function renderDirectorGuide() {
    if (!els.directorHints) return;
    if (!state.story) {
        els.directorHints.innerHTML = `
            <div class="guide-kicker">演示流程</div>
            <div class="guide-title">先新建或选择一个故事</div>
            <div class="guide-meta">准备好故事后，Director Agent 会按当前状态选择下一步工具。</div>
        `;
        return;
    }
    const prompt = getSuggestedDirectorPrompt();
    const outlines = (state.story.outlines || []).length;
    const chapters = Object.keys(state.story.chapters || {}).length;
    const pending = (state.story.foreshadowings || []).filter(item => item.status === "pending").length;
    els.directorHints.innerHTML = `
        <div class="guide-kicker">推荐下一步</div>
        <button type="button" class="guide-suggestion" data-director-suggest="${escapeHtml(prompt)}">
            <i data-lucide="sparkles"></i><span>${escapeHtml(prompt)}</span>
        </button>
        <div class="guide-meta">${outlines} 章大纲 · ${chapters} 章正文 · ${pending} 个未回收伏笔</div>
    `;
    const button = els.directorHints.querySelector("[data-director-suggest]");
    if (button) {
        button.addEventListener("click", () => {
            els.directorInput.value = prompt;
            els.directorInput.focus();
        });
    }
}

function getSuggestedDirectorPrompt() {
    if (!state.story) return "新建一个故事并生成大纲";
    const outlines = state.story.outlines || [];
    const chapters = state.story.chapters || {};
    if (!outlines.length) return "先生成 10 章大纲";
    const nextOutline = outlines.find(outline => !getChapter(outline.chapter_index)?.content);
    if (nextOutline) return `继续写第${nextOutline.chapter_index}章`;
    const pending = (state.story.foreshadowings || []).filter(item => item.status === "pending").length;
    if (pending) return "查看未回收伏笔并给出处理建议";
    return `检查第${state.activeChapter}章人物有没有崩`;
}

function renderContextPreview() {
    if (!els.contextPreview) return;
    if (!state.story) {
        els.contextPreview.innerHTML = `<div class="context-empty">选择故事后展示本章写作上下文。</div>`;
        return;
    }
    const outline = getOutline(state.activeChapter);
    const chapter = getChapter(state.activeChapter);
    const summary = state.story.chapter_summaries?.[state.activeChapter] || state.story.chapter_summaries?.[String(state.activeChapter)];
    const characters = Object.values(state.story.characters || {}).slice(0, 4);
    const pendingForeshadowings = (state.story.foreshadowings || [])
        .filter(item => item.status === "pending" || item.status === "overdue")
        .slice(0, 4);
    const memoryCards = (state.story.memory_cards || [])
        .slice()
        .sort((left, right) => (Number(right.importance || 0) - Number(left.importance || 0)))
        .slice(0, 4);
    const beats = chapter?.beats || [];
    const blocks = [
        contextBlock("本章大纲", outline ? [
            outline.title,
            outline.summary,
            outline.conflict ? `冲突：${outline.conflict}` : "",
            outline.pov_character ? `POV：${outline.pov_character}` : "",
        ].filter(Boolean) : []),
        contextBlock("场景节拍", beats.map(beat => `${beat.scene_index}. ${beat.description} → ${beat.outcome}`).slice(0, 5)),
        contextBlock("角色资产", characters.map(character => {
            const pieces = [character.name, character.personality, character.motivation].filter(Boolean);
            return pieces.join(" · ");
        })),
        contextBlock("未回收伏笔", pendingForeshadowings.map(item => {
            const target = item.target_chapter ? ` / 目标第${item.target_chapter}章` : "";
            return `${item.description}${target}`;
        })),
        contextBlock("近期摘要", summary ? [
            summary.chapter_summary,
            ...(summary.scene_summaries || []).slice(0, 2),
        ].filter(Boolean) : []),
        contextBlock("记忆卡片", memoryCards.map(card => {
            const label = card.type ? `[${card.type}] ` : "";
            return `${label}${card.content || card.summary || card.id || ""}`;
        })),
    ];
    els.contextPreview.innerHTML = blocks.join("");
}

function contextBlock(title, items) {
    const rows = (items || []).filter(Boolean).map(item => `<li>${escapeHtml(truncateText(item, 130))}</li>`);
    const body = rows.length ? `<ul>${rows.join("")}</ul>` : `<div class="context-empty">暂无</div>`;
    return `
        <div class="context-block">
            <div class="context-title">${escapeHtml(title)}</div>
            ${body}
        </div>
    `;
}

function runGuideAction(action) {
    if (action === "focus-premise") {
        els.newPremise.focus();
        setStatus("先填写故事前提，再点击新建");
        return;
    }
    if (action === "focus-outline") {
        els.outlineStrip.scrollIntoView({ block: "nearest", behavior: "smooth" });
        setStatus("请先选择有大纲的章节");
        return;
    }
    if (action === "outline") {
        generateOutline();
        return;
    }
    if (action === "beats") {
        generateBeats();
        return;
    }
    if (action === "write") {
        writeChapter();
        return;
    }
    if (action === "director") {
        if (!els.directorInput.value.trim()) {
            els.directorInput.value = getSuggestedDirectorPrompt();
        }
        runDirectorAgent();
    }
}

function renderEvents() {
    const events = (state.story?.causal_events || []).slice(-8).reverse();
    els.eventLog.innerHTML = events.length ? events.map(event => `
        <div class="event-row">第${event.chapter}章 · ${escapeHtml(event.description)}</div>
    `).join("") : `<div class="event-row">No events</div>`;
}

function renderJobEvents(job) {
    state.lastJobEvents = job.events || [];
    renderAgentTrace(job);
    const rows = state.lastJobEvents.slice(-12).reverse().map(event => {
        const chapter = event.chapter_index ? `ch${event.chapter_index} · ` : "";
        const agent = event.agent ? `${event.agent}${event.action ? `/${event.action}` : ""} · ` : "";
        const progress = event.progress_total ? ` (${event.progress_current || 0}/${event.progress_total})` : "";
        return `<div class="event-row">${escapeHtml(chapter)}${escapeHtml(agent)}${escapeHtml(event.message || event.stage || "Working")}${escapeHtml(progress)}</div>`;
    });
    els.eventLog.innerHTML = rows.length ? rows.join("") : `<div class="event-row">${escapeHtml(job.message || job.status || "Working")}</div>`;
}

async function generateOutline() {
    if (!state.story) {
        setStatus("请先新建或选择故事");
        return;
    }
    const count = Math.max(1, Number(prompt("章节数", "10") || "10"));
    let force = false;
    if ((state.story.outlines || []).length) {
        force = confirm("已有大纲，是否覆盖重建？取消则只补齐缺失章节。");
    }
    setStatus("Generating outline");
    await postJson(`/stories/${state.story.id}/outline`, { num_chapters: count, force });
    await loadStory(state.story.id);
}

async function generateBeats() {
    if (!state.story) {
        setStatus("请先新建或选择故事");
        return;
    }
    if (!getOutline(state.activeChapter)) {
        setStatus("请先生成或选择本章大纲");
        return;
    }
    const chapterIndex = state.activeChapter;
    setStatus("Generating beats");
    await postJson(`/chapters/${chapterIndex}/beats?story_id=${state.story.id}`, {});
    await loadStory(state.story.id);
    state.activeChapter = chapterIndex;
    renderWorkspace();
}

async function writeChapter() {
    if (!state.story) {
        setStatus("请先新建或选择故事");
        return;
    }
    if (!getOutline(state.activeChapter)) {
        setStatus("请先生成本章大纲");
        return;
    }
    setStatus("Writing chapter");
    await postJson(`/chapters/${state.activeChapter}/write?story_id=${state.story.id}`, {});
    await loadStory(state.story.id);
}

async function batchWrite() {
    if (!state.story || !(state.story.outlines || []).length) {
        setStatus("批量写作前需要先有章节大纲");
        return;
    }
    const start = Number(prompt("起始章节", String(state.activeChapter)) || state.activeChapter);
    const end = Number(prompt("结束章节", String(Math.max(start, start + 2))) || start);
    const useAuto = confirm("是否启用自动审查修订？点“确定”为自动修订，点“取消”为只写草稿。");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return;
    setStatus(`Batch ${start}-${end}`);
    const job = await postJson(`/stories/${state.story.id}/batch-write`, {
        start_chapter: start,
        end_chapter: end,
        use_auto_revision: useAuto,
        background: true,
    });
    state.activeJob = job.id;
    pollJob();
}

async function agenticRun() {
    if (!state.story || !(state.story.outlines || []).length) {
        setStatus("批量编排前需要先有章节大纲");
        return;
    }
    const objective = prompt("Agent objective", `Write chapters from ${state.activeChapter} with planning, review, continuity audit, and memory updates.`);
    if (!objective) return;
    const start = Number(prompt("Start chapter", String(state.activeChapter)) || state.activeChapter);
    const end = Number(prompt("End chapter", String(Math.max(start, start + 2))) || start);
    const useAuto = confirm("Use autonomous review and revision for each chapter?");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return;
    setStatus(`Agent run ${start}-${end}`);
    const job = await postJson(`/stories/${state.story.id}/agentic-run`, {
        objective,
        start_chapter: start,
        end_chapter: end,
        use_auto_revision: useAuto,
        background: true,
    });
    state.activeJob = job.id;
    pollJob();
}

async function runDirectorAgent() {
    if (!state.story) {
        setStatus("请先选择或新建故事");
        return;
    }
    let message = els.directorInput.value.trim();
    if (!message) {
        message = getSuggestedDirectorPrompt();
        els.directorInput.value = message;
    }
    setDirectorRunning(true);
    renderAgentTrace({
        steps: [],
        status: "running",
        final_summary: "Director Agent 正在分析故事状态并选择工具...",
    });
    try {
        const run = await postJson(`/stories/${state.story.id}/agent/run`, {
            user_message: message,
            max_steps: 6,
        });
        await loadStory(state.story.id);
        renderAgentTrace(run);
        renderDirectorResult(run);
        setStatus(run.status || "Director Agent finished");
    } catch (error) {
        renderAgentTrace({
            steps: [{
                step: 1,
                selected_tool: "director_agent",
                reasoning_summary: "运行失败",
                tool_args: { user_message: message },
                observation: "",
                error: error.message || String(error),
                success: false,
            }],
            status: "failed",
            final_summary: "Director Agent 没有完成本次任务。",
        });
        setStatus("Director Agent failed");
    } finally {
        setDirectorRunning(false);
    }
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
    if (!state.story || !getChapter(state.activeChapter)?.content?.trim()) {
        setStatus("审查前需要先写出正文");
        return;
    }
    setStatus("Reviewing");
    const payload = await postJson(`/chapters/${state.activeChapter}/review?story_id=${state.story.id}`, {});
    const validation = await postJson(`/chapters/${state.activeChapter}/validate-contract?story_id=${state.story.id}`, {});
    renderReview(payload.report, validation);
    setStatus("Ready");
}

async function autoWrite() {
    if (!state.story || !getChapter(state.activeChapter)?.content?.trim()) {
        setStatus("自修前需要先写出正文");
        return;
    }
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
        const progressCurrent = job.progress_current ?? job.current_round ?? 0;
        const progressTotal = job.progress_total ? `/${job.progress_total}` : "";
        els.jobStatus.textContent = `${job.status} · ${progressCurrent}${progressTotal} · ${job.message || "Working"}`;
        renderJobEvents(job);
        if (["passed", "failed", "stopped", "finished_with_residual_issues", "batch_finished", "batch_finished_with_failures", "agentic_finished", "agentic_finished_with_failures"].includes(job.status)) {
            clearInterval(state.polling);
            if (job.result) renderReport(job.result);
            if (job.batch_result) renderBatchResult(job.batch_result);
            if (job.autonomous_result) renderAgenticResult(job.autonomous_result);
            if (job.autonomous_result) renderAgentTrace(job.autonomous_result);
            await loadStory(state.story.id);
        }
    }, 1200);
}

function renderAgenticResult(report) {
    renderAgentTrace(report);
    const rows = [
        `<div class="score-row"><strong>${escapeHtml(report.status)}</strong> · ${report.completed_tasks}/${(report.tasks || []).length} tasks · ${report.failed_tasks} failed</div>`
    ];
    for (const task of report.tasks || []) {
        const chapter = task.chapter_index ? `ch${task.chapter_index}: ` : "";
        rows.push(`<div class="event-row">${escapeHtml(chapter)}${escapeHtml(task.agent)} / ${escapeHtml(task.action)} · ${escapeHtml(task.status)} · ${escapeHtml(task.output_summary || task.error || task.reason || "")}</div>`);
    }
    els.qualityReport.innerHTML = rows.join("");
}

function renderAgentTrace(source = null) {
    if (!els.agentTrace) return;
    const directorRun = source?.steps ? source : latestDirectorRun();
    if (directorRun && (directorRun.steps?.length || directorRun.status === "running")) {
        const header = `
            <div class="trace-summary">
                <div>
                    <strong>Director Agent</strong>
                    <div class="trace-meta">${escapeHtml(directorRun.user_message || els.directorInput?.value || "自然语言任务")}</div>
                </div>
                <span>${escapeHtml(directorRun.status || "completed")} · ${(directorRun.steps || []).length} steps</span>
            </div>
        `;
        const rows = (directorRun.steps || []).map(step => {
            const state = step.success ? "completed" : "failed";
            const args = Object.keys(step.tool_args || {}).length ? JSON.stringify(step.tool_args, null, 2) : "{}";
            return `
                <div class="trace-row ${state}">
                    <div class="trace-top">
                        <span>Step ${step.step}</span>
                        <strong>${escapeHtml(step.selected_tool)}</strong>
                    </div>
                    <div class="trace-meta">${step.success ? "success" : "error"}</div>
                    <div class="trace-text"><strong>Reason</strong>${escapeHtml(step.reasoning_summary || "")}</div>
                    <details class="trace-args">
                        <summary>tool_args</summary>
                        <pre>${escapeHtml(args)}</pre>
                    </details>
                    <div class="trace-text"><strong>Observation</strong>${escapeHtml(step.observation || step.error || "")}</div>
                </div>
            `;
        }).join("");
        const running = directorRun.status === "running" ? `
            <div class="trace-row running">
                <div class="trace-top"><span>Running</span><strong>thinking</strong></div>
                <div class="trace-text">正在读取故事状态、选择工具并执行。</div>
            </div>
        ` : "";
        const final = directorRun.final_summary ? `
            <div class="trace-final">
                <strong>Final Summary</strong>
                <div>${escapeHtml(directorRun.final_summary)}</div>
            </div>
        ` : "";
        els.agentTrace.innerHTML = header + running + rows + final;
        return;
    }
    const run = source?.autonomous_result || (source?.tasks ? source : latestAgenticRun());
    if (run?.tasks?.length) {
        const header = `
            <div class="trace-summary">
                <strong>${escapeHtml(run.planning_strategy || "agentic")}</strong>
                <span>${escapeHtml(run.status || "planned")} · ${run.completed_tasks || 0}/${run.tasks.length}</span>
            </div>
            ${run.planning_notes ? `<div class="trace-note">${escapeHtml(run.planning_notes)}</div>` : ""}
        `;
        const rows = run.tasks.map(task => {
            const chapter = task.chapter_index ? `ch${task.chapter_index}` : "story";
            const note = task.output_summary || task.error || task.reason || "";
            return `
                <div class="trace-row ${escapeHtml(task.status || "pending")}">
                    <div class="trace-top">
                        <span>${task.step_index}. ${escapeHtml(task.agent)}</span>
                        <strong>${escapeHtml(task.action)}</strong>
                    </div>
                    <div class="trace-meta">${escapeHtml(chapter)} · ${escapeHtml(task.status || "pending")}</div>
                    <div class="trace-text">${escapeHtml(note)}</div>
                </div>
            `;
        }).join("");
        els.agentTrace.innerHTML = header + rows;
        return;
    }
    const events = source?.events || state.lastJobEvents || [];
    const agentEvents = events.filter(event => event.agent || event.action).slice(-8).reverse();
    if (agentEvents.length) {
        els.agentTrace.innerHTML = agentEvents.map(event => `
            <div class="trace-row running">
                <div class="trace-top">
                    <span>${escapeHtml(event.agent || "Agent")}</span>
                    <strong>${escapeHtml(event.action || event.stage || "working")}</strong>
                </div>
                <div class="trace-meta">${event.chapter_index ? `ch${event.chapter_index}` : "story"} · live</div>
                <div class="trace-text">${escapeHtml(event.message || "Working")}</div>
            </div>
        `).join("");
        return;
    }
    const prompt = getSuggestedDirectorPrompt();
    els.agentTrace.innerHTML = `
        <div class="trace-empty">
            <strong>还没有 Agent Trace</strong>
            <button type="button" data-empty-director-prompt="${escapeHtml(prompt)}">
                <i data-lucide="sparkles"></i><span>${escapeHtml(prompt)}</span>
            </button>
        </div>
    `;
    const button = els.agentTrace.querySelector("[data-empty-director-prompt]");
    if (button) {
        button.addEventListener("click", () => {
            els.directorInput.value = prompt;
            runDirectorAgent();
        });
    }
    renderIcons();
}

function latestDirectorRun() {
    const runs = state.story?.agent_trace_runs || [];
    return runs.length ? runs[runs.length - 1] : null;
}

function latestAgenticRun() {
    const runs = state.story?.agent_runs || [];
    return runs.length ? runs[runs.length - 1] : null;
}

function renderDirectorResult(run) {
    const rows = [
        `<div class="score-row"><strong>${escapeHtml(run.status || "completed")}</strong> · ${escapeHtml(run.final_summary || "")}</div>`
    ];
    for (const step of run.steps || []) {
        rows.push(`<div class="event-row">Step ${step.step}: ${escapeHtml(step.selected_tool)} · ${step.success ? "success" : "error"} · ${escapeHtml(step.observation || step.error || "")}</div>`);
    }
    els.qualityReport.innerHTML = rows.join("");
}

function renderBatchResult(report) {
    const rows = [
        `<div class="score-row"><strong>${report.completed}</strong> completed · ${report.failed} failed · ch${report.start_chapter}-${report.end_chapter}</div>`
    ];
    for (const item of report.results || []) {
        const score = item.auto_revision_score == null ? "" : ` · score ${Number(item.auto_revision_score).toFixed(2)}`;
        rows.push(`<div class="event-row">ch${item.chapter_index}: ${escapeHtml(item.status)}${score} · ${escapeHtml(item.title || item.message || "")}</div>`);
    }
    els.qualityReport.innerHTML = rows.join("");
}

async function loadReport() {
    if (!state.story || !getChapter(state.activeChapter)?.content?.trim()) {
        setStatus("报告需要先有正文或审查结果");
        return;
    }
    const report = await getJson(`/chapters/${state.activeChapter}/report?story_id=${state.story.id}`);
    if (report.error) {
        renderReport(null);
        return;
    }
    renderReport(report);
}

function renderReview(report, validation = null) {
    const issues = [
        ...(report.logic_issues || []).map(description => ({ severity: "medium", dimension: "逻辑", description })),
        ...(report.character_issues || []).map(description => ({ severity: "medium", dimension: "人设", description })),
        ...(report.pacing_issues || []).map(description => ({ severity: "medium", dimension: "节奏", description })),
    ];
    const rows = [];
    if (validation) {
        rows.push(`<div class="score-row"><strong>合同验收</strong> · ${validation.passed ? "passed" : validation.review_required ? "需要人工确认" : "failed"}</div>`);
        for (const check of validation.checks || []) rows.push(contractCheckRow(check));
    }
    if (issues.length) rows.push(...issues.map(issueRow));
    if (!rows.length) rows.push(`<div class="score-row"><strong>${escapeHtml(report.verdict || "reviewed")}</strong></div>`);
    els.qualityReport.innerHTML = rows.join("");
}

function renderReport(report) {
    if (!report) {
        const saved = state.story?.auto_revision_reports?.[state.activeChapter];
        const continuity = state.story?.continuity_reports?.[state.activeChapter];
        report = saved || (continuity ? { continuity_report: continuity } : null);
    }
    if (!report) {
        els.qualityReport.innerHTML = `<div class="score-row">No report</div>`;
        return;
    }
    const rows = [];
    if (report.final_score != null || report.rounds) {
        rows.push(`<div class="score-row"><strong>${Number(report.final_score || 0).toFixed(2)}</strong> · ${report.passed ? "passed" : "not passed"}</div>`);
        for (const round of report.rounds || []) {
            rows.push(`<div class="score-row">Round ${round.round}: <strong>${Number(round.total_score || 0).toFixed(2)}</strong></div>`);
            for (const check of round.review_report?.contract_checks || []) rows.push(contractCheckRow(check));
            for (const issue of round.review_report?.issues || []) rows.push(issueRow(issue));
        }
        for (const issue of report.residual_issues || []) rows.push(issueRow(issue));
    }
    const continuity = report.continuity_report || report;
    if (continuity && continuity.risk_score != null) {
        rows.push(`<div class="score-row">Continuity risk: <strong>${Number(continuity.risk_score || 0).toFixed(1)}</strong> · ${continuity.passed ? "passed" : "risk"}</div>`);
        for (const issue of continuity.issues || []) rows.push(issueRow(issue));
    }
    els.qualityReport.innerHTML = rows.join("");
}

function issueRow(issue) {
    return `<div class="issue-row ${escapeHtml(issue.severity || "medium")}">[${escapeHtml(issue.dimension || "-")}] ${escapeHtml(issue.description || "")}</div>`;
}

function contractCheckRow(check) {
    const status = check.status || (check.passed ? "passed" : "failed");
    const confidence = check.validation_method === "rule+llm" ? ` · 置信度 ${Math.round(Number(check.confidence || 0) * 100)}%` : " · 规则检查";
    const location = check.paragraph_range ? ` · ${escapeHtml(check.paragraph_range)}` : "";
    const evidence = check.evidence ? `<blockquote>${escapeHtml(check.evidence)}</blockquote>` : "";
    return `<div class="contract-check ${escapeHtml(status)}">`
        + `<div><strong>${escapeHtml(check.requirement || "-")}</strong></div>`
        + `<small>${escapeHtml(status)}${confidence}${location}</small>`
        + `<div>${escapeHtml(check.message || "")}</div>${evidence}</div>`;
}

function openDashboard() {
    if (!state.story) return;
    window.open(`/dashboard/?story_id=${state.story.id}`, "_blank");
}

function exportDocx() {
    if (!state.story) return;
    setStatus("Exporting Word");
    const a = document.createElement("a");
    a.href = `/stories/${state.story.id}/export-docx`;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setStatus("Ready");
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

async function deleteJson(url) {
    const response = await fetch(url, { method: "DELETE" });
    if (!response.ok) throw new Error(`${response.status} ${url}`);
    return response.json();
}

function setDirectorRunning(running) {
    state.directorRunning = running;
    updateActionAvailability();
    if (els.directorRunBtn) {
        els.directorRunBtn.querySelector("span").textContent = running ? "运行中" : "运行 Agent";
    }
}

function updateActionAvailability() {
    const hasStory = Boolean(state.story);
    const hasOutlines = Boolean(state.story?.outlines?.length);
    const hasOutline = Boolean(getOutline(state.activeChapter));
    const hasContent = Boolean(getChapter(state.activeChapter)?.content?.trim());
    setButtonState(els.outlineBtn, hasStory, "请先新建或选择故事");
    setButtonState(els.writeBtn, hasOutline, hasStory ? "写作前需要先有本章大纲" : "请先新建或选择故事");
    setButtonState(els.saveBtn, hasStory, "请先新建或选择故事");
    setButtonState(els.exportDocxBtn, hasStory, "请先新建或选择故事");
    setButtonState(els.dashboardBtn, hasStory, "请先新建或选择故事");
    setButtonState(els.directorRunBtn, hasStory && !state.directorRunning, state.directorRunning ? "Agent 正在运行" : "请先新建或选择故事");
    setButtonState(els.agentRunBtn, hasStory && !state.directorRunning, state.directorRunning ? "Agent 正在运行" : "请先新建或选择故事");
    setButtonState(els.beatsBtn, hasOutline, hasStory ? "细纲前需要先有本章大纲" : "请先新建或选择故事");
    setButtonState(els.reviewBtn, hasContent, hasStory ? "审查前需要先写出正文" : "请先新建或选择故事");
    setButtonState(els.autoBtn, hasContent, hasStory ? "自修前需要先写出正文" : "请先新建或选择故事");
    setButtonState(els.reportBtn, hasContent, hasStory ? "报告需要正文或审查结果" : "请先新建或选择故事");
    setButtonState(els.batchBtn, hasOutlines, hasStory ? "批量写作前需要先有章节大纲" : "请先新建或选择故事");
    setButtonState(els.agenticRunBtn, hasOutlines, hasStory ? "批量编排前需要先有章节大纲" : "请先新建或选择故事");
}

function setButtonState(button, enabled, disabledReason) {
    if (!button) return;
    button.disabled = !enabled;
    button.classList.toggle("is-disabled", !enabled);
    button.title = enabled ? "" : disabledReason;
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

function truncateText(value, maxLength = 120) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (text.length <= maxLength) return text;
    return `${text.slice(0, maxLength - 1)}…`;
}
