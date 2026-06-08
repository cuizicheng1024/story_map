import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import StoryMap from "./components/StoryMap";
import HomeGraph from "./components/HomeGraph";
import peopleNames from "./data/pep_people_merged.json";
import { fetchTaskStatus, submitGenerateTask } from "./utils/backend";

const MAX_INPUT_LEN = 200;
const POLL_INTERVAL_MS = 1200;
const TASK_TIMEOUT_MS = 5 * 60 * 1000;
const historyItems = ["曹操", "李白", "苏轼", "康熙", "唐三藏"];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function buildMapMessageFromTask(taskSnapshot) {
  const summary = taskSnapshot?.result;
  const resultItems = Array.isArray(summary?.results) ? summary.results : [];
  const firstSuccess = resultItems.find((item) => item?.ok && item?._profile);
  const profile = firstSuccess?._profile;

  if (!profile) {
    throw new Error(summary?.conclusion || "服务端未返回可展示的人物结果。");
  }

  const person = profile?.person?.name || firstSuccess?.person || "人物";
  const intro = profile?.person?.description || "";
  const locations = Array.isArray(profile?.locations)
    ? profile.locations
        .map((loc) => ({
          name: loc?.name || loc?.modernName || loc?.ancientName || "未命名地点",
          lat: loc?.lat,
          lng: loc?.lng,
          type: loc?.type || "normal",
          time: loc?.time || "",
          desc: [loc?.event, loc?.significance].filter(Boolean).join("；"),
          quotes: Array.isArray(loc?.quoteLines) ? loc.quoteLines : []
        }))
        .filter((loc) => Number.isFinite(loc.lat) && Number.isFinite(loc.lng))
    : [];

  if (!locations.length) {
    throw new Error(`服务端已生成「${person}」，但未返回可用坐标。`);
  }

  return { person, intro, locations };
}

function buildProgressText(taskSnapshot) {
  const queue = taskSnapshot?.queue || {};
  const progress = Array.isArray(taskSnapshot?.progress) ? taskSnapshot.progress : [];
  const latest = progress.length ? progress[progress.length - 1] : null;

  if (taskSnapshot?.status === "queued") {
    const position = queue?.position || 1;
    const limit = queue?.limit || 1;
    return `任务已提交，正在排队（前方 ${position - 1} 个，最大并发 ${limit}）...`;
  }

  if (latest?.detail) {
    return `${latest.label}：${latest.detail}`;
  }
  if (latest?.label) {
    return `${latest.label}...`;
  }
  return "服务端正在处理，请稍候...";
}

export default function App() {
  const [messages, setMessages] = useState([
    {
      id: crypto.randomUUID(),
      type: "text",
      role: "assistant",
      text: "输入历史人物名称，我会检索相关事件并生成人物简介和足迹地图。"
    }
  ]);
  const [inputValue, setInputValue] = useState("");
  const [homeSearch, setHomeSearch] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [loadingText, setLoadingText] = useState("服务端正在处理，请稍候...");
  const chatEndRef = useRef(null);

  const quickResults = useMemo(() => {
    const q = homeSearch.trim();
    if (!q) return peopleNames.slice(0, 10);
    return peopleNames.filter((x) => String(x).includes(q)).slice(0, 10);
  }, [homeSearch]);

  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const appendMessage = useCallback((payload) => {
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), ...payload }]);
  }, []);

  const handleGenerate = async (text) => {
    if (!text.trim()) return;
    if (isLoading) return;

    setIsLoading(true);
    setLoadingText("任务提交中...");
    appendMessage({ type: "text", role: "user", text });

    try {
      const submitResult = await submitGenerateTask(text.trim());
      const taskId = submitResult?.task_id;
      if (!taskId) {
        throw new Error("服务端没有返回任务 ID。");
      }

      const startAt = Date.now();
      let snapshot = null;

      while (Date.now() - startAt < TASK_TIMEOUT_MS) {
        snapshot = await fetchTaskStatus(taskId);
        setLoadingText(buildProgressText(snapshot));

        if (snapshot?.status === "completed") {
          const mapPayload = buildMapMessageFromTask(snapshot);
          appendMessage({
            type: "map",
            role: "assistant",
            person: mapPayload.person,
            locations: mapPayload.locations,
            intro: mapPayload.intro
          });
          return;
        }

        if (snapshot?.status === "failed") {
          throw new Error(snapshot?.error || "服务端生成失败。");
        }

        await sleep(POLL_INTERVAL_MS);
      }
      throw new Error("等待服务端结果超时，请稍后重试。");
    } catch (e) {
      console.error(e);
      appendMessage({ type: "text", role: "assistant", text: `发生错误: ${e.message}` });
    } finally {
      setIsLoading(false);
      setLoadingText("服务端正在处理，请稍候...");
    }
  };

  const onSend = () => {
    handleGenerate(inputValue);
    setInputValue("");
  };

  const onHistoryClick = (item) => {
    handleGenerate(item);
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <header className="flex-none px-6 py-4 bg-white border-b shadow-sm z-10">
        <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
          🗺️ StoryMap <span className="text-xs font-normal text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">从空间视角重新发现历史人物生命轨迹</span>
        </h1>
      </header>

      {/* Chat Area */}
      <main className="flex-1 overflow-y-auto p-4 custom-scrollbar">
        <div className="max-w-3xl mx-auto space-y-6">
          <section className="bg-white border border-amber-100 rounded-xl p-4 shadow-sm">
            <h2 className="text-lg font-bold text-gray-800 mb-2">首页入口：搜索 + 人物知识图谱</h2>
            <div className="flex gap-2 mb-3">
              <input
                type="text"
                value={homeSearch}
                onChange={(e) => setHomeSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && quickResults.length) handleGenerate(quickResults[0]);
                }}
                placeholder="搜索人教版人物（例如：吴道子、玄奘、文天祥）"
                className="flex-1 px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-amber-400"
              />
              <button
                onClick={() => quickResults.length && handleGenerate(quickResults[0])}
                disabled={!quickResults.length || isLoading}
                className="px-4 py-2 rounded-lg bg-amber-500 text-white disabled:opacity-50"
              >
                生成地图
              </button>
            </div>
            <div className="flex flex-wrap gap-2 mb-3">
              {quickResults.map((name) => (
                <button
                  key={name}
                  onClick={() => handleGenerate(name)}
                  disabled={isLoading}
                  className="px-2 py-1 text-xs rounded-full bg-amber-100 text-amber-800 hover:bg-amber-200 disabled:opacity-50"
                >
                  {name}
                </button>
              ))}
            </div>
            <HomeGraph names={peopleNames} query={homeSearch} onSelect={handleGenerate} />
          </section>

          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[90%] md:max-w-[80%] rounded-2xl p-4 shadow-sm ${
                msg.role === "user" 
                  ? "bg-blue-600 text-white rounded-tr-sm" 
                  : "bg-white border border-gray-100 rounded-tl-sm"
              }`}>
                {msg.type === "text" && (
                  <p className="whitespace-pre-wrap leading-relaxed">{msg.text}</p>
                )}
                
                {msg.type === "map" && (
                  <div className="space-y-3">
                    <div className="flex items-baseline gap-2 border-b pb-2 mb-2">
                      <h2 className="text-lg font-bold text-gray-900">{msg.person}</h2>
                      <span className="text-xs text-gray-500">共 {msg.locations.length} 个足迹点</span>
                    </div>
                    {msg.intro && <p className="text-sm text-gray-600 mb-3">{msg.intro}</p>}
                    <div className="w-full h-[400px] rounded-lg overflow-hidden border border-gray-200 relative">
                       <StoryMap locations={msg.locations} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
          {isLoading && (
             <div className="flex justify-start">
               <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-sm p-4 shadow-sm">
                 <p className="mb-3 text-sm text-gray-600">{loadingText}</p>
                 <div className="flex space-x-2">
                   <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0s' }}></div>
                   <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                   <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
                 </div>
               </div>
             </div>
          )}
          <div ref={chatEndRef} />
        </div>
      </main>

      {/* Input Area */}
      <footer className="flex-none bg-white border-t p-4">
        <div className="max-w-3xl mx-auto space-y-4">
          {/* History Chips */}
          <div className="flex flex-wrap gap-2">
            {historyItems.map((item) => (
              <button
                key={item}
                onClick={() => onHistoryClick(item)}
                disabled={isLoading}
                className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-full transition-colors disabled:opacity-50"
              >
                {item}
              </button>
            ))}
          </div>
          
          {/* Input Box */}
          <div className="relative">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value.slice(0, MAX_INPUT_LEN))}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && onSend()}
              placeholder="输入历史人物名称..."
              disabled={isLoading}
              className="w-full pl-4 pr-12 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white transition-all disabled:opacity-60"
            />
            <button
              onClick={onSend}
              disabled={!inputValue.trim() || isLoading}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-blue-600 hover:bg-blue-50 rounded-lg disabled:text-gray-400 disabled:hover:bg-transparent transition-colors"
            >
              <svg className="w-5 h-5 rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
          <div className="text-center text-xs text-gray-400">
            StoryMap V1.0 • Web Powered by Python Backend
          </div>
        </div>
      </footer>
    </div>
  );
}
