const $ = (id) => document.getElementById(id);
const state = { story: null, chapter: null, tab: "report" };

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
  return payload;
}

function setStatus(message) { $("status").textContent = message; }
function storyId() { return state.story?.id; }
function chapterIndex() { return Number($("chapterSelect").value); }

async function refreshStories() {
  const { stories } = await request("/dashboard/stories");
  $("storySelect").innerHTML = '<option value="">选择已有故事</option>' + stories.map(
    item => `<option value="${item.id}">${item.title}</option>`
  ).join("");
}

async function loadStory(id) {
  if (!id) return;
  const { story } = await request(`/stories/${id}/`);
  state.story = story;
  $("storySelect").value = id;
  $("dashboardLink").href = `/dashboard/?story_id=${id}`;
  $("chapterSelect").innerHTML = '<option value="">选择章节</option>' + story.design.outlines.map(
    item => `<option value="${item.chapter_index}">${item.chapter_index}. ${item.title}</option>`
  ).join("");
  setStatus(`${story.title} · ${story.status} · 当前第 ${story.current_chapter} 章`);
  const preferred = state.chapter || story.current_chapter || story.design.outlines[0]?.chapter_index;
  if (preferred) { $("chapterSelect").value = preferred; showChapter(preferred); }
  await showInspector();
}

function showChapter(index) {
  state.chapter = Number(index);
  const outline = state.story?.design.outlines.find(item => item.chapter_index === state.chapter);
  const chapter = state.story?.manuscript.chapters?.[state.chapter];
  $("outlineCard").classList.toggle("empty", !outline);
  $("outlineCard").textContent = outline
    ? `${outline.title}\n\n${outline.summary}\n\n核心冲突：${outline.conflict}`
    : "该章节没有大纲。";
  $("chapterTitle").value = chapter?.title || outline?.title || "";
  $("chapterContent").value = chapter?.content || "";
  showInspector();
}

async function showInspector() {
  if (!state.story) return;
  let payload;
  if (state.tab === "storage") payload = await request(`/stories/${storyId()}/storage`);
  else if (state.tab === "knowledge") payload = state.story.knowledge;
  else if (chapterIndex()) payload = await request(`/chapters/${chapterIndex()}/report?story_id=${storyId()}`);
  else payload = { message: "请选择章节。" };
  $("inspectorOutput").textContent = JSON.stringify(payload, null, 2);
}

async function run(label, action) {
  try { setStatus(`${label}…`); await action(); setStatus(`${label}完成`); }
  catch (error) { setStatus(`${label}失败：${error.message}`); }
}

$("createBtn").onclick = () => run("创建故事", async () => {
  const payload = await request("/stories/", { method: "POST", body: JSON.stringify({ title: $("titleInput").value || "未命名故事", premise: $("premiseInput").value }) });
  await refreshStories(); await loadStory(payload.story.id);
});
$("storySelect").onchange = event => loadStory(event.target.value);
$("outlineBtn").onclick = () => run("生成大纲", async () => {
  await request(`/stories/${storyId()}/outline`, { method: "POST", body: JSON.stringify({ num_chapters: Number($("chapterCount").value), force: false }) });
  await loadStory(storyId());
});
$("chapterSelect").onchange = event => showChapter(event.target.value);
$("beatsBtn").onclick = () => run("规划场景", async () => {
  await request(`/chapters/${chapterIndex()}/beats?story_id=${storyId()}`, { method: "POST", body: "{}" }); await loadStory(storyId());
});
$("writeBtn").onclick = () => run("可靠生成", async () => {
  await request(`/chapters/${chapterIndex()}/write?story_id=${storyId()}`, { method: "POST", body: "{}" }); await loadStory(storyId());
});
$("reviewBtn").onclick = () => run("章节评审", async () => {
  await request(`/chapters/${chapterIndex()}/review?story_id=${storyId()}`, { method: "POST", body: "{}" }); await loadStory(storyId());
});
$("saveBtn").onclick = () => run("保存人工编辑", async () => {
  await request(`/chapters/${chapterIndex()}/content?story_id=${storyId()}`, { method: "PUT", body: JSON.stringify({ title: $("chapterTitle").value, content: $("chapterContent").value, status: "draft" }) }); await loadStory(storyId());
});
$("finalizeBtn").onclick = () => run("章节定稿", async () => {
  await request(`/chapters/${chapterIndex()}/finalize?story_id=${storyId()}`, { method: "POST", body: "{}" }); await loadStory(storyId());
});
$("batchBtn").onclick = () => run("批量写作", async () => {
  await request(`/stories/${storyId()}/batch-write`, { method: "POST", body: JSON.stringify({ start_chapter: chapterIndex() || 1, end_chapter: Number($("chapterCount").value) }) }); await loadStory(storyId());
});
$("exportBtn").onclick = () => { if (storyId()) window.location.href = `/stories/${storyId()}/export-docx`; };
document.querySelectorAll(".tab").forEach(button => button.onclick = () => {
  document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
  button.classList.add("active"); state.tab = button.dataset.tab; showInspector();
});

(async () => {
  await refreshStories();
  const initial = document.body.dataset.storyId;
  if (initial) await loadStory(initial);
})();
