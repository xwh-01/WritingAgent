let dashboardData = null;
let characterChart = null;
let pacingChart = null;
let qualityChart = null;
let causalityChart = null;

const palette = {
    accent: "#0f766e",
    amber: "#b45309",
    danger: "#b91c1c",
    green: "#15803d",
    text: "#202124",
    muted: "#6b6b64",
    line: "#ded9cf",
};

document.addEventListener("DOMContentLoaded", async () => {
    await hydrateStorySelector();
    const selected = window.NOVELFORGE_STORY_ID || document.getElementById("storySelector").value;
    if (selected) {
        await loadStory(selected);
    } else {
        showEmptyState(true);
    }
});

async function hydrateStorySelector() {
    const selector = document.getElementById("storySelector");
    selector.innerHTML = "<option value=\"\">选择故事...</option>";
    try {
        const response = await fetch("/dashboard/stories");
        const payload = await response.json();
        for (const story of payload.stories || []) {
            const option = document.createElement("option");
            option.value = story.id;
            option.textContent = `${story.title} · 第${story.current_chapter}章`;
            selector.appendChild(option);
        }
        if (window.NOVELFORGE_STORY_ID) {
            selector.value = window.NOVELFORGE_STORY_ID;
        } else if (payload.stories?.length) {
            selector.value = payload.stories[0].id;
        }
    } catch (error) {
        console.error(error);
    }
    selector.addEventListener("change", () => {
        if (selector.value) {
            const url = new URL(window.location.href);
            url.searchParams.set("story_id", selector.value);
            window.history.replaceState({}, "", url);
            loadStory(selector.value);
        }
    });
}

async function loadStory(storyId) {
    showEmptyState(false);
    const response = await fetch(`/dashboard/data/${storyId}`);
    if (!response.ok) {
        showEmptyState(true);
        return;
    }
    dashboardData = await response.json();
    renderAll();
}

function renderAll() {
    renderOverview();
    renderForeshadowings();
    renderCharacterSelector();
    renderPacing();
    renderQualityTrend();
    renderCausality();
}

function renderOverview() {
    const overview = dashboardData.story_overview;
    document.getElementById("storyTitle").textContent = overview.title;
    document.getElementById("storyPremise").textContent = overview.premise || "暂无故事前提";

    const cards = [
        ["类型", overview.genre],
        ["章节", `${overview.current_chapter}/${overview.total_chapters || 0}`],
        ["草稿", overview.drafted_chapters],
        ["定稿", overview.completed_chapters],
        ["伏笔待回收", overview.foreshadowing_pending],
        ["质量报告", overview.auto_report_count],
    ];
    document.getElementById("overviewCards").innerHTML = cards.map(([label, value]) => (
        `<article class="stat-card"><div class="value">${escapeHtml(String(value))}</div><div class="label">${label}</div></article>`
    )).join("");
}

function renderForeshadowings() {
    const rows = dashboardData.foreshadowings;
    const pending = rows.filter(item => item.status === "pending").length;
    const overdue = rows.filter(item => item.status === "overdue").length;
    const fulfilled = rows.filter(item => item.status === "fulfilled").length;
    document.getElementById("foreshadowSummary").textContent = `${fulfilled} 已回收 · ${pending} 待回收 · ${overdue} 逾期`;

    const tbody = document.getElementById("foreshadowTable");
    if (!rows.length) {
        tbody.innerHTML = "<tr><td colspan=\"6\">暂无伏笔记录</td></tr>";
        return;
    }
    tbody.innerHTML = rows.map(item => {
        const label = statusLabel(item.status);
        return `<tr>
            <td>${escapeHtml(item.id)}</td>
            <td>${escapeHtml(item.description)}</td>
            <td>第${item.created_chapter}章</td>
            <td>${item.target_chapter ? `第${item.target_chapter}章` : "未指定"}</td>
            <td><span class="status status-${item.status}">${label}</span></td>
            <td>${escapeHtml(item.notes || "")}</td>
        </tr>`;
    }).join("");
}

function renderCharacterSelector() {
    const selector = document.getElementById("charSelector");
    const names = Object.keys(dashboardData.character_timeline);
    selector.innerHTML = names.length
        ? names.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")
        : "<option value=\"\">暂无角色状态</option>";
    selector.onchange = renderCharacterChart;
    renderCharacterChart();
}

function renderCharacterChart() {
    const selector = document.getElementById("charSelector");
    const name = selector.value;
    const timeline = dashboardData.character_timeline[name] || [];
    const dom = document.getElementById("characterChart");
    characterChart = characterChart || echarts.init(dom);
    if (!timeline.length) {
        characterChart.setOption(emptyChartOption("暂无角色状态数据"), true);
        return;
    }
    const chapters = timeline.map(item => `第${item.chapter}章`);
    const emotionLabels = unique(timeline.map(item => item.emotion || "未知"));
    const locationLabels = unique(timeline.map(item => item.location || "未知"));
    characterChart.setOption({
        tooltip: {
            trigger: "axis",
            formatter: params => {
                const index = params[0].dataIndex;
                const item = timeline[index];
                return `${chapters[index]}<br>情绪：${escapeHtml(item.emotion || "未知")}<br>位置：${escapeHtml(item.location || "未知")}`;
            },
        },
        grid: { left: 48, right: 48, top: 42, bottom: 40 },
        legend: { data: ["情绪", "位置"], textStyle: { color: palette.muted } },
        xAxis: { type: "category", data: chapters, axisLabel: { color: palette.muted } },
        yAxis: [
            { type: "category", data: emotionLabels, axisLabel: { color: palette.muted } },
            { type: "category", data: locationLabels, axisLabel: { color: palette.muted } },
        ],
        series: [
            {
                name: "情绪",
                type: "line",
                smooth: true,
                data: timeline.map(item => emotionLabels.indexOf(item.emotion || "未知")),
                itemStyle: { color: palette.accent },
            },
            {
                name: "位置",
                type: "scatter",
                yAxisIndex: 1,
                symbolSize: 11,
                data: timeline.map(item => locationLabels.indexOf(item.location || "未知")),
                itemStyle: { color: palette.amber },
            },
        ],
    }, true);
}

function renderPacing() {
    const data = dashboardData.pacing_heatmap;
    const dom = document.getElementById("pacingChart");
    pacingChart = pacingChart || echarts.init(dom);
    if (!data.length) {
        pacingChart.setOption(emptyChartOption("暂无章节节奏数据"), true);
        return;
    }
    pacingChart.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: 42, right: 36, top: 42, bottom: 42 },
        legend: { data: ["冲突强度", "对话密度", "行动密度"], textStyle: { color: palette.muted } },
        xAxis: { type: "category", data: data.map(item => `第${item.chapter}章`), axisLabel: { color: palette.muted } },
        yAxis: { type: "value", axisLabel: { color: palette.muted } },
        series: [
            { name: "冲突强度", type: "bar", data: data.map(item => item.conflict_intensity), itemStyle: { color: palette.accent } },
            { name: "对话密度", type: "line", data: data.map(item => item.dialogue_ratio), itemStyle: { color: palette.amber } },
            { name: "行动密度", type: "line", data: data.map(item => item.action_ratio), itemStyle: { color: palette.danger } },
        ],
    }, true);
}

function renderQualityTrend() {
    const data = dashboardData.quality_trend || [];
    const dom = document.getElementById("qualityChart");
    qualityChart = qualityChart || echarts.init(dom);
    if (!data.length) {
        qualityChart.setOption(emptyChartOption("暂无自动修订评分数据"), true);
        return;
    }
    const labels = data.map(item => `第${item.chapter}章 R${item.round}`);
    qualityChart.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: 42, right: 36, top: 42, bottom: 42 },
        legend: { data: ["总分", "逻辑", "人设", "伏笔", "节奏", "风格"], textStyle: { color: palette.muted } },
        xAxis: { type: "category", data: labels, axisLabel: { color: palette.muted } },
        yAxis: { type: "value", min: 0, max: 10, axisLabel: { color: palette.muted } },
        series: [
            { name: "总分", type: "line", smooth: true, data: data.map(item => item.total_score), itemStyle: { color: palette.accent }, lineStyle: { width: 3 } },
            { name: "逻辑", type: "line", data: data.map(item => item.logic_consistency), itemStyle: { color: "#1d4ed8" } },
            { name: "人设", type: "line", data: data.map(item => item.character_fidelity), itemStyle: { color: "#7c3aed" } },
            { name: "伏笔", type: "line", data: data.map(item => item.foreshadowing_handling), itemStyle: { color: palette.amber } },
            { name: "节奏", type: "line", data: data.map(item => item.pacing), itemStyle: { color: palette.danger } },
            { name: "风格", type: "line", data: data.map(item => item.style_uniformity), itemStyle: { color: palette.green } },
        ],
    }, true);
}

function renderCausality() {
    const graph = dashboardData.causality_graph;
    const dom = document.getElementById("causalityChart");
    causalityChart = causalityChart || echarts.init(dom);
    document.getElementById("causalitySummary").textContent = `${graph.nodes.length} 事件 · ${graph.edges.length} 关系`;
    if (!graph.nodes.length) {
        causalityChart.setOption(emptyChartOption("暂无因果事件"), true);
        return;
    }
    causalityChart.setOption({
        tooltip: {
            formatter: item => item.data.description || item.data.name || "",
        },
        series: [{
            type: "graph",
            layout: "force",
            data: graph.nodes.map(node => ({
                id: node.id,
                name: node.label,
                chapter: node.chapter,
                description: node.description,
                symbolSize: 34,
                itemStyle: { color: colorForChapter(node.chapter) },
            })),
            links: graph.edges.map(edge => ({
                source: edge.source,
                target: edge.target,
                label: { show: true, formatter: edge.relation === "causes" ? "导致" : "影响" },
            })),
            roam: true,
            label: { show: true, position: "right", color: palette.text, fontSize: 11 },
            force: { repulsion: 360, edgeLength: 150 },
            lineStyle: { color: palette.line, curveness: 0.22, width: 1.5 },
            edgeSymbol: ["none", "arrow"],
            edgeSymbolSize: 8,
        }],
    }, true);
}

function emptyChartOption(text) {
    return {
        title: { text, left: "center", top: "middle", textStyle: { color: palette.muted, fontSize: 14 } },
        xAxis: { show: false },
        yAxis: { show: false },
        series: [],
    };
}

function showEmptyState(show) {
    document.getElementById("emptyState").hidden = !show;
    document.querySelector("main").hidden = show;
}

function statusLabel(status) {
    return ({ pending: "待回收", fulfilled: "已回收", abandoned: "废弃", overdue: "逾期" })[status] || status;
}

function unique(values) {
    return [...new Set(values)];
}

function colorForChapter(chapter) {
    const colors = ["#0f766e", "#b45309", "#1d4ed8", "#7c3aed", "#be123c"];
    return colors[Math.abs(chapter || 0) % colors.length];
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

window.addEventListener("resize", () => {
    characterChart?.resize();
    pacingChart?.resize();
    qualityChart?.resize();
    causalityChart?.resize();
});
