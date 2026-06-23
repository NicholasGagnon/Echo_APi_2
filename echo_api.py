"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { supabase } from "./lib/supabase";
import { checkQuota, getMessageMaxLength, UserTier } from "../utils/quota";
import LangDropdown from "./components/LangDropdown";
import TutorialHeaderControls from "./components/TutorialHeaderControls";
import { useApp } from "../context/AppContext";

type HistoryEntry = { id: string; title: string; date: string; messages: string[] };
type EchoMessage  = { raw: string; imageB64?: string };
type StickyNote   = { id: string; text: string; color: "yellow"|"blue"|"green"|"pink" };
type CalendarEvent  = { id: string; title: string; start: string; end: string; notes: string };
type CalendarEvents = Record<string, CalendarEvent[]>;
type UpcomingEvent  = CalendarEvent & { dateKey: string; diffDays: number };

const normalizeTier = (raw: unknown): UserTier => {
  if (typeof raw !== "string") return "connected_free";
  const c = raw.toLowerCase().trim();
  if (c === "free" || c === "connected_free") return "connected_free";
  const valid: UserTier[] = ["connected_free","basic","premium","ultra","founder"];
  return valid.includes(c as UserTier) ? (c as UserTier) : "connected_free";
};

const fetchUserTier = async (uid: string): Promise<UserTier> => {
  const { data, error } = await supabase.from("profiles").select("user_tier").eq("id", uid).single();
  if (!error && data?.user_tier) return normalizeTier(data.user_tier);
  return "connected_free";
};

const STICKY_STYLES = {
  yellow: { bg:"bg-yellow-950/40 dark:bg-yellow-950", border:"border-yellow-600/50", text:"text-yellow-900 dark:text-yellow-200", dot:"bg-yellow-400" },
  blue:   { bg:"bg-blue-950/40 dark:bg-blue-950",     border:"border-blue-500/50",   text:"text-blue-900 dark:text-blue-200",   dot:"bg-blue-400"   },
  green:  { bg:"bg-green-950/40 dark:bg-green-950",  border:"border-green-600/50",  text:"text-green-900 dark:text-green-200", dot:"bg-green-400"  },
  pink:   { bg:"bg-pink-950/40 dark:bg-pink-950",     border:"border-pink-600/50",   text:"text-pink-900 dark:text-pink-200",   dot:"bg-pink-400"   },
};

const EVENT_DOT_COLORS = ["bg-cyan-400","bg-green-400","bg-yellow-400"];

const WATER = [
  { g:"〰", top:"6%",  left:"1%",   rot:"-18deg", sz:"58px" },
  { g:"∿",  top:"20%", right:"2%",  rot:"12deg",  sz:"70px" },
  { g:"〜", top:"44%", left:"0.5%", rot:"-8deg",  sz:"50px" },
  { g:"≈",  top:"67%", right:"1.5%",rot:"18deg",  sz:"64px" },
  { g:"∾",  top:"83%", left:"2%",   rot:"-12deg", sz:"54px" },
];

const deriveTitle = (raws: string[], lang: string): string => {
  const first = raws.find(r => /^(You|Toi)\s*:/i.test(r));
  if (first) {
    const clean = first.replace(/^(You|Toi)\s*:\s*/i,"").trim();
    if (clean) return clean.length > 42 ? `${clean.slice(0,42)}…` : clean;
  }
  return lang === "fr" ? "Nouvelle conversation" : "New conversation";
};

export default function Home() {
  const { t, lang, theme, toggleTheme, triggerToast } = useApp();

  const [message,   setMessage]   = useState("");
  const [messages,  setMessages]  = useState<EchoMessage[]>([]);
  const [isLoaded,  setIsLoaded]  = useState(false);
  const [userId,    setUserId]    = useState<string|null>(null);
  const [activeConvId, setActiveConvId] = useState<string|null>(null);

  const bottomRef     = useRef<HTMLDivElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const textareaRef   = useRef<HTMLTextAreaElement>(null);
  const saveTimerRef  = useRef<ReturnType<typeof setTimeout>|null>(null);

  const [isListening,       setIsListening]       = useState(false);
  const [selectedImage,      setSelectedImage]      = useState<string|null>(null);
  const [selectedImageName, setSelectedImageName]  = useState("");

  const DEFAULT_INPUT_HEIGHT = 112;
  const [inputHeight, setInputHeight] = useState(DEFAULT_INPUT_HEIGHT);

  const shrinkInput = () => {
    const el = textareaRef.current;
    const cur = el ? el.getBoundingClientRect().height : inputHeight;
    const next = Math.max(48, Math.round(cur / 2));
    if (el) el.style.height = `${next}px`;
    setInputHeight(next);
  };
  const resetInput = () => {
    if (textareaRef.current) textareaRef.current.style.height = `${DEFAULT_INPUT_HEIGHT}px`;
    setInputHeight(DEFAULT_INPUT_HEIGHT);
  };

  // ── PANELS ────────────────────────────────────────────────────────────────
  const [leftPanelWidth,  setLeftPanelWidth]  = useState(220);
  const [rightPanelWidth, setRightPanelWidth] = useState(272);
  const [isDesktop, setIsDesktop] = useState(false);
  const resizingSideRef = useRef<"left"|"right"|null>(null);

  useEffect(() => {
    const sl = parseInt(localStorage.getItem("echo-home-left-width")  || "", 10);
    const sr = parseInt(localStorage.getItem("echo-home-panel-width") || "", 10);
    if (Number.isFinite(sl)) setLeftPanelWidth(Math.min(340,Math.max(180,sl)));
    if (Number.isFinite(sr)) setRightPanelWidth(Math.min(440,Math.max(220,sr)));
    const check = () => setIsDesktop(window.innerWidth >= 1024);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const startPanelResize = (side: "left"|"right") => (e: React.MouseEvent) => {
    e.preventDefault();
    resizingSideRef.current = side;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const s = resizingSideRef.current;
      if (!s) return;
      if (s === "left") setLeftPanelWidth(Math.min(340, Math.max(180, e.clientX)));
      else setRightPanelWidth(Math.min(440, Math.max(220, window.innerWidth - e.clientX)));
    };
    const onUp = () => {
      if (!resizingSideRef.current) return;
      resizingSideRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  useEffect(() => { localStorage.setItem("echo-home-left-width",  String(leftPanelWidth));  }, [leftPanelWidth]);
  useEffect(() => { localStorage.setItem("echo-home-panel-width", String(rightPanelWidth)); }, [rightPanelWidth]);

  // ── STATE ─────────────────────────────────────────────────────────────────
  const [stickies,       setStickies]       = useState<StickyNote[]>([]);
  const [newStickyText,  setNewStickyText]  = useState("");
  const [selectedColor,  setSelectedColor]  = useState<StickyNote["color"]>("yellow");
  const [expandedSticky, setExpandedSticky] = useState<StickyNote|null>(null);
  const [editText,       setEditText]       = useState("");

  const [calendarEvents, setCalendarEvents] = useState<CalendarEvents>({});
  const [userTier,       setUserTier]       = useState<UserTier>("connected_free");
  const [echoState,      setEchoState]      = useState("idle");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [tutorialStep,   setTutorialStep]   = useState<number|null>(null);
  const [selectedButtons,        setSelectedButtons]        = useState<string[]>([]);
  const [isDoubleRegardUnlocked, setIsDoubleRegardUnlocked] = useState(false);
  const [showLimitModal,        setShowLimitModal]    = useState(false);
  const [activeLimitCategory, setActiveLimitCategory] = useState<"vitality_actions"|"calendar">("vitality_actions");

  const localButtonsLabels: Record<"fr"|"en", Record<string,string>> = {
    fr: { clarity:"1🧠 Clarté", humain:"2👤 Humain", critical:"3⚔️ Regard critique", expert:"4🎓 Expert", precision:"5🎯 Précision", philosophy:"6🏛️ Philosophie", strategy:"7♟️ Stratégie", decompose:"8🧩 Décomposer", refine:"9❓ Affiner", double:"10⚡ Double Regard" },
    en: { clarity:"1🧠 Clarity", humain:"2👤 Human", critical:"3⚔️ Critical View", expert:"4🎓 Expert", precision:"5🎯 Precision", philosophy:"6🏛️ Philosophy", strategy:"7♟️ Strategy", decompose:"8🧩 Decompose", refine:"9❓ Refine", double:"10⚡ Double Regard" },
  };
  const buttonsData = ["clarity","humain","critical","expert","precision","philosophy","strategy","decompose","refine","double"].map(id => ({ id }));

  const handleButtonClick = (id: string) => {
    if (id === "double") { if (selectedButtons.length === 1) setIsDoubleRegardUnlocked(true); return; }
    if (selectedButtons.includes(id)) {
      const next = selectedButtons.filter(b => b !== id);
      setSelectedButtons(next);
      if (next.length < 2) setIsDoubleRegardUnlocked(false);
    } else {
      if (selectedButtons.length === 0) { setSelectedButtons([id]); setIsDoubleRegardUnlocked(false); }
      else if (selectedButtons.length === 1 && isDoubleRegardUnlocked) setSelectedButtons(p => [...p, id]);
    }
  };

  const serializeMsgs   = (msgs: EchoMessage[]) => msgs.map(m => m.raw);
  const deserializeMsgs = (raws: string[]): EchoMessage[] => raws.map(r => ({ raw: r }));
  const lastEchoIndex   = messages.findLastIndex(m => /^Echo\s*:/i.test(m.raw));

  // ── SAVE TO SUPABASE ──────────────────────────────────────────────────────
  const saveToSupabase = async (uid: string, convId: string|null, raws: string[]): Promise<string|null> => {
    if (convId) {
      await supabase.from("echo_conversations")
        .update({ messages: raws, updated_at: new Date().toISOString() })
        .eq("id", convId).eq("user_id", uid);
      return convId;
    } else {
      const { data, error } = await supabase.from("echo_conversations")
        .insert({ user_id: uid, source: "chat", messages: raws, updated_at: new Date().toISOString() })
        .select("id").single();
      if (error) { console.error("[Home] insert conv:", error.message); return null; }
      return data?.id ?? null;
    }
  };

  // ── BOOTSTRAP ─────────────────────────────────────────────────────────────
  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      const uid = session?.user?.id || null;
      setUserId(uid);

      try {
        if (uid) {
          const { data: convRows } = await supabase
            .from("echo_conversations")
            .select("id, messages")
            .eq("user_id", uid)
            .eq("source", "chat")
            .order("updated_at", { ascending: false })
            .limit(1);

          if (convRows?.length) {
            setActiveConvId(convRows[0].id);
            setMessages(deserializeMsgs(convRows[0].messages || []));
          }

          const { data: stickyRows } = await supabase
            .from("echo_stickies").select("*").eq("user_id", uid)
            .order("created_at", { ascending: true });
          if (stickyRows?.length)
            setStickies(stickyRows.map(r => ({ id: r.id, text: r.text, color: r.color as StickyNote["color"] })));

          const { data: calRows } = await supabase
            .from("echo_calendar").select("*").eq("user_id", uid);
          if (calRows?.length) {
            const rebuilt: CalendarEvents = {};
            calRows.forEach(r => {
              const key = r.start_date;
              if (!rebuilt[key]) rebuilt[key] = [];
              rebuilt[key].push({ id: r.id, title: r.title, start: r.start_time||"", end: r.end_time||"", notes: r.notes||"" });
            });
            setCalendarEvents(rebuilt);
          }

          setUserTier(await fetchUserTier(uid));
        } else {
          const saved = localStorage.getItem("echo-conversation-v2");
          if (saved) setMessages(deserializeMsgs(JSON.parse(saved)));
        }

        const isTutoDone = localStorage.getItem("echo-tuto-done-v1");
        if (!isTutoDone) setTutorialStep(1);

      } catch(e) { console.error("Bootstrap error", e); }
      setIsLoaded(true);
    });

    const { data: listener } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (event === "SIGNED_OUT" || !session?.user) {
        setUserId(null); setCalendarEvents({}); setStickies([]);
        setMessages([]); setUserTier("connected_free"); setActiveConvId(null);
        return;
      }
      if (session?.user) {
        const uid = session.user.id;
        setUserId(uid);
        const { data: convRows } = await supabase
          .from("echo_conversations").select("id, messages")
          .eq("user_id", uid).eq("source", "chat")
          .order("updated_at", { ascending: false }).limit(1);
        if (convRows?.length) {
          setActiveConvId(convRows[0].id);
          setMessages(deserializeMsgs(convRows[0].messages || []));
        }
        setUserTier(await fetchUserTier(uid));
      }
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  // ── AUTOSAVE ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!isLoaded) return;
    const raws = serializeMsgs(messages);

    if (userId) {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(async () => {
        const newId = await saveToSupabase(userId, activeConvId, raws);
        if (newId && !activeConvId) setActiveConvId(newId);
      }, 1500);
    } else {
      localStorage.setItem("echo-conversation-v2", JSON.stringify(raws));
    }

    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
  }, [messages, isLoaded]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // ── UPCOMING EVENTS ───────────────────────────────────────────────────────
  const upcomingEvents: UpcomingEvent[] = (() => {
    const today = new Date(); today.setHours(0,0,0,0);
    const results: UpcomingEvent[] = [];
    for (const [dateKey, evts] of Object.entries(calendarEvents)) {
      const d = new Date(dateKey + "T00:00:00");
      const diffDays = Math.floor((d.getTime() - today.getTime()) / 86400000);
      if (diffDays >= 0 && diffDays <= 30) evts.forEach(ev => results.push({ ...ev, dateKey, diffDays }));
    }
    return results.sort((a,b) => a.diffDays - b.diffDays).slice(0,6);
  })();

  // ── IMAGE ─────────────────────────────────────────────────────────────────
  const compressImage = (base64: string): Promise<string> =>
    new Promise(resolve => {
      const img = document.createElement("img");
      img.onload = () => {
        const MAX = 1200; let w = img.width, h = img.height;
        if (w > MAX || h > MAX) { if (w > h) { h = Math.round(h*MAX/w); w = MAX; } else { w = Math.round(w*MAX/h); h = MAX; } }
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        canvas.getContext("2d")!.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", 0.75));
      };
      img.src = base64;
    });

  // ── ENVOYER — /home est ILLIMITÉ, pas de checkQuota sur les messages ──────
  const envoyer = async () => {
    if (!message.trim() && !selectedImage) return;

    const userMessage  = message.trim();
    const currentImage = selectedImage;
    const currentName  = selectedImageName;
    const userRaw = userMessage
      ? `You: ${userMessage}`
      : `You: ${lang === "fr" ? "Analyse cette image" : "Analyze this image"}${currentName ? ` (${currentName})` : ""}.`;

    const userEntry: EchoMessage = { raw: userRaw, imageB64: currentImage ?? undefined };
    const baseMessages = [...messages, userEntry];
    setEchoState("thinking");
    setMessages([...baseMessages, { raw: "Echo: ..." }]);
    setMessage(""); setSelectedImage(null); setSelectedImageName("");

    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000";
      const response = await fetch(`${API_URL}/home`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMessage || `${lang === "fr" ? "Analyse cette image" : "Analyze this image"}${currentName ? ` (${currentName})` : ""}.`,
          image: currentImage ?? null,
          history: serializeMsgs(baseMessages),
          userTier,
          calendarEvents,
          selectedButtons,
        }),
      });

      const data = await response.json();
      setEchoState("speaking");

      // Quota uniquement sur les ACTIONS automatiques (calendar / vitality_actions)
      let isActionBlocked = false;
      let blockedCategory: "vitality_actions"|"calendar"|null = null;
      if (data.action) {
        const { type } = data.action;
        const qCat: "vitality_actions"|"calendar" = (type === "ADD_BUDGET_EXPENSE" || type === "ADD_CALORIE_LOG") ? "vitality_actions" : "calendar";
        const status = checkQuota(qCat, userTier);
        if (!status.allowed) { setActiveLimitCategory(qCat); setShowLimitModal(true); isActionBlocked = true; blockedCategory = qCat; }
      }

      const echoText = data.response || "";
      const actionNotice = isActionBlocked ? `\n\n[🔒 Action bloquée par quota "${blockedCategory}"]` : "";
      setMessages([...baseMessages, { raw: `Echo: ${echoText}${actionNotice}` }]);

      if (data.action && !isActionBlocked) {
        const { type, payload } = data.action;

        if (type === "ADD_BUDGET_EXPENSE") {
          const { title, amount, spent, date, paymentDate, paidAt } = payload;
          const finalTitle = title || "Achat";
          const finalAmount = parseFloat(amount ?? spent) || 0;
          const finalDate = paymentDate || paidAt || date || new Date().toLocaleDateString("fr-CA");
          if (userId) {
            const { error } = await supabase.from("echo_expenses").insert({ user_id: userId, title: finalTitle, amount: finalAmount, date: finalDate });
            if (error) triggerToast("error", lang === "fr" ? `Erreur dépense : ${error.message}` : `Expense error: ${error.message}`);
            else triggerToast("info", lang === "fr" ? `📈 Dépense de ${finalAmount}$ ajoutée !` : `📈 Expense of ${finalAmount}$ added!`);
          }
        }

        if (type === "ADD_CALORIE_LOG") {
          const { foodName, title, food_name, calories } = payload;
          const finalFoodName = title || foodName || food_name || "Aliment";
          const finalCalories = parseInt(calories) || 0;
          if (userId) {
            const { error } = await supabase.from("echo_calories").insert({ user_id: userId, food_name: finalFoodName, calories: finalCalories, date: new Date().toLocaleDateString("fr-CA") });
            if (error) triggerToast("error", lang === "fr" ? `Erreur calorie : ${error.message}` : `Calorie error: ${error.message}`);
            else triggerToast("info", lang === "fr" ? `🍎 ${finalFoodName} (${finalCalories} kcal) ajouté !` : `🍎 ${finalFoodName} (${finalCalories} kcal) added!`);
          }
        }

        if (type === "SET_CALORIE_GOAL" || type === "UPDATE_CALORIE_GOAL") {
          const { goal, calorieGoal, calories } = payload;
          const nextGoal = parseInt(goal ?? calorieGoal ?? calories);
          if (Number.isFinite(nextGoal) && nextGoal > 0) {
            localStorage.setItem("echo-calorie-goal", nextGoal.toString());
            triggerToast("info", lang === "fr" ? `🎯 Objectif : ${nextGoal} kcal` : `🎯 Goal: ${nextGoal} kcal`);
          }
        }

        if (type === "ADD_CALENDAR_EVENT") {
          const { title, start, end, notes } = payload;
          const dateKey = start?.split("T")[0] || start || "";
          const finalTitle = title || "Rendez-vous sans titre";
          const finalNotes = notes || "";

          if (dateKey && userId) {
            try {
              const { data: insertedList, error } = await supabase.from("echo_calendar").insert({
                user_id: userId, title: finalTitle, start_date: dateKey, end_date: dateKey, notes: finalNotes, is_from_echo: true,
              }).select();

              let finalId = `temp-${Date.now()}`;
              if (error) {
                const { data: retryList, error: retryError } = await supabase.from("echo_calendar").insert({
                  user_id: userId, title: finalTitle, start_date: dateKey, end_date: dateKey, notes: finalNotes,
                }).select();
                if (!retryError && retryList?.length) finalId = retryList[0].id;
              } else if (insertedList?.length) {
                finalId = insertedList[0].id;
              }

              let extractedStart = "";
              const timeMatch = finalNotes.match(/(?:Heure\s*:\s*)?(\d{1,2}h(?:\d{2})?\s*(?:à|to)\s*\d{1,2}h(?:\d{2})?)/i);
              if (timeMatch) extractedStart = timeMatch[1];

              setCalendarEvents(prev => {
                const currentList = prev[dateKey] || [];
                if (currentList.some(ev => ev.title === finalTitle && ev.notes === finalNotes)) return prev;
                return { ...prev, [dateKey]: [...currentList, { id: finalId, title: finalTitle, start: extractedStart, end: "", notes: finalNotes }] };
              });

              triggerToast("info", lang === "fr" ? `📅 Événement "${finalTitle}" ajouté !` : `📅 Event "${finalTitle}" added!`);
            } catch (err: any) {
              console.error("[Home] Crash insertion calendrier :", err);
            }
          }
        }
      }
    } catch {
      setMessages([...baseMessages, { raw: "Echo: Impossible de joindre le serveur." }]);
    } finally {
      setTimeout(() => setEchoState("idle"), 10000);
    }
  };

  // ── STICKIES ──────────────────────────────────────────────────────────────
  const addSticky = async () => {
    if (!newStickyText.trim()) return;
    if (!userId) {
      const id = `local-${Date.now()}`;
      setStickies(prev => [...prev, { id, text: newStickyText.trim(), color: selectedColor }]);
      setNewStickyText("");
      return;
    }
    const { data: inserted, error } = await supabase.from("echo_stickies").insert({
      user_id: userId, text: newStickyText.trim(), color: selectedColor,
    }).select().single();
    if (error) { console.error("[Home] echo_stickies insert:", error.message); return; }
    setStickies(prev => [...prev, { id: inserted.id, text: inserted.text, color: inserted.color }]);
    setNewStickyText("");
  };

  const deleteSticky = async (id: string) => {
    if (userId && !id.startsWith("local-")) {
      const { error } = await supabase.from("echo_stickies").delete().eq("id", id).eq("user_id", userId);
      if (error) console.error("[Home] echo_stickies delete:", error.message);
    }
    setStickies(prev => prev.filter(s => s.id !== id));
  };

  const saveStickyEdit = async () => {
    if (!expandedSticky) return;
    if (userId && !expandedSticky.id.startsWith("local-")) {
      const { error } = await supabase.from("echo_stickies")
        .update({ text: editText }).eq("id", expandedSticky.id).eq("user_id", userId);
      if (error) console.error("[Home] echo_stickies update:", error.message);
    }
    setStickies(prev => prev.map(s => s.id === expandedSticky.id ? { ...s, text: editText } : s));
    setExpandedSticky(null);
  };

  // ── MISC ──────────────────────────────────────────────────────────────────
  const isImageButtonLocked = userTier === "connected_free" || userTier === "basic";

  const lancerDictation = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { alert("Speech recognition is not supported."); return; }
    const recognition = new SR();
    recognition.lang = lang === "fr" ? "fr-FR" : "en-US";
    recognition.onstart  = () => setIsListening(true);
    recognition.onend    = () => setIsListening(false);
    recognition.onresult = (e: any) => setMessage(p => p + (p?" ":"") + e.results[0][0].transcript);
    recognition.start();
  };

  const handleImageSelection = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; event.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) { alert(lang==="fr"?"Choisis un fichier image.":"Please choose an image file."); return; }
    if (file.size > 5*1024*1024) { alert(lang==="fr"?"L'image doit faire moins de 5 Mo.":"The image must be smaller than 5 MB."); return; }
    const reader = new FileReader();
    reader.onload = async () => { const c = await compressImage(reader.result as string); setSelectedImage(c); setSelectedImageName(file.name); };
    reader.readAsDataURL(file);
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (isImageButtonLocked) return;
    const items = event.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        const file = items[i].getAsFile(); if (!file) continue;
        event.preventDefault();
        if (file.size > 5*1024*1024) { alert(lang==="fr"?"L'image doit faire moins de 5 Mo.":"The image must be smaller than 5 MB."); return; }
        const reader = new FileReader();
        reader.onload = async () => { const c = await compressImage(reader.result as string); setSelectedImage(c); setSelectedImageName(`screenshot-${Date.now()}.png`); };
        reader.readAsDataURL(file);
        return;
      }
    }
  };

  const diffDaysLabel = (d: number) => {
    if (d === 0) return lang==="fr"?"Aujourd'hui":"Today";
    if (d === 1) return lang==="fr"?"Demain":"Tomorrow";
    return lang==="fr"?`Dans ${d} jours`:`In ${d} days`;
  };

  useEffect(() => {
    const handleOutsideClick = () => setIsSettingsOpen(false);
    if (isSettingsOpen) window.addEventListener("click", handleOutsideClick);
    return () => window.removeEventListener("click", handleOutsideClick);
  }, [isSettingsOpen]);

  // ── RENDER ────────────────────────────────────────────────────────────────
  return (
    <main className="h-screen bg-white dark:bg-black text-black dark:text-white flex overflow-hidden relative font-sans transition-colors duration-200 selection:bg-cyan-500/30">
      <div className="flex flex-1 overflow-hidden min-h-0">

        {/* NAV SIDEBAR */}
        <aside
          style={isDesktop ? { width: leftPanelWidth, flexBasis: leftPanelWidth } : undefined}
          className="w-55 shrink-0 border-r border-zinc-200 dark:border-zinc-800 p-8 bg-zinc-50 dark:bg-zinc-950 flex flex-col justify-between">
          <div className="space-y-20">
            <h2 className="font-bold text-lg">
              <Link href="/" className="text-cyan-600 dark:text-cyan-400 font-bold">{t.sidebar.home}</Link>
            </h2>
            <div className="space-y-20 text-zinc-800 dark:text-zinc-100 font-medium">
              <Link href="/chat"     className="block hover:text-cyan-500">{t.sidebar.chat}</Link>
              <Link href="/books"    className="block hover:text-cyan-500">{t.sidebar.books}</Link>
              <Link href="/calendar" className="block hover:text-cyan-500">📅 {lang==="fr"?"Calendrier":"Calendar"}</Link>
              <Link href="/vitality" className="block hover:text-cyan-500">📈 {lang==="fr"?"Vitalité":"Vitality"}</Link>
              <Link href="/services" className="block hover:text-cyan-500">💎 {lang==="fr"?"Services":"Services"}</Link>
              <Link href="/account"  className="block hover:text-cyan-500">👤 {lang==="fr"?"Compte":"Account"}</Link>
              <Link href="/horizonweb" className="block hover:text-cyan-500">📡 HorizonWeb</Link>
              <hr className="border-zinc-200 dark:border-zinc-800 my-4" />
              <Link href="/history"  className="block hover:text-amber-500">⭐ {lang==="fr"?"Historique":"History"}</Link>
            </div>
          </div>
          <div className="pt-4 border-t border-zinc-200 dark:border-zinc-800 text-xs text-zinc-500">
            Status : <span className="text-cyan-500 dark:text-cyan-400 uppercase font-bold block">{userTier}</span>
          </div>
        </aside>

        <div onMouseDown={startPanelResize("left")} className="hidden lg:flex w-2.5 shrink-0 cursor-col-resize items-center justify-center group">
          <div className="w-1 h-12 rounded-full bg-zinc-200 dark:bg-zinc-800 group-hover:bg-cyan-500 transition-colors" />
        </div>

        <div className="flex-1 flex flex-col lg:flex-row overflow-hidden min-h-0">

          {/* MAIN SECTION */}
          <section className="flex-1 flex flex-col p-4 min-w-0 overflow-hidden relative">

            {/* DASHBOARD ECHO — TOUJOURS VISIBLE EN HAUT */}
            <div className="w-full shrink-0 flex items-center justify-center gap-3 xl:gap-5 py-3">

              {/* GAUCHE : CALENDRIER + BUDGET */}
              <div className="flex gap-3 shrink-0">
                <Link href="/calendar" className="group relative w-24 h-24 flex flex-col items-center justify-center gap-1.5 rounded-2xl border transition-all duration-300 overflow-hidden select-none"
                  style={{background:"linear-gradient(135deg,rgba(59,130,246,0.12) 0%,rgba(37,99,235,0.05) 100%)",borderColor:"rgba(59,130,246,0.35)",boxShadow:"0 0 20px rgba(59,130,246,0.1),inset 0 1px 0 rgba(59,130,246,0.2)"}}>
                  <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" style={{background:"linear-gradient(135deg,rgba(59,130,246,0.2) 0%,rgba(59,130,246,0.08) 100%)"}}/>
                  <div className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity" style={{background:"linear-gradient(90deg,transparent,rgba(59,130,246,1),transparent)"}}/>
                  <div className="absolute top-1.5 left-1.5 w-1.5 h-1.5 border-t border-l border-blue-400/50"/><div className="absolute bottom-1.5 right-1.5 w-1.5 h-1.5 border-b border-r border-blue-400/50"/>
                  <svg className="relative z-10 w-9 h-9" viewBox="0 0 64 64" fill="none">
                    <rect x="6" y="10" width="52" height="48" rx="8" fill="rgba(59,130,246,0.15)" stroke="rgba(59,130,246,0.6)" strokeWidth="2"/>
                    <rect x="6" y="10" width="52" height="20" rx="8" fill="rgba(59,130,246,0.4)"/>
                    <rect x="6" y="22" width="52" height="8" fill="rgba(59,130,246,0.4)"/>
                    <circle cx="20" cy="8" r="4" fill="rgba(59,130,246,0.8)"/><circle cx="44" cy="8" r="4" fill="rgba(59,130,246,0.8)"/>
                    <rect x="14" y="36" width="8" height="7" rx="2" fill="rgba(59,130,246,0.7)"/>
                    <rect x="28" y="36" width="8" height="7" rx="2" fill="rgba(59,130,246,0.5)"/>
                    <rect x="42" y="36" width="8" height="7" rx="2" fill="rgba(59,130,246,0.5)"/>
                    <rect x="14" y="47" width="8" height="5" rx="2" fill="rgba(59,130,246,0.3)"/>
                    <rect x="28" y="47" width="8" height="5" rx="2" fill="rgba(59,130,246,0.3)"/>
                  </svg>
                  <span className="relative z-10 text-[8px] font-mono font-black tracking-widest uppercase text-blue-400">{lang==="fr"?"CALENDRIER":"CALENDAR"}</span>
                </Link>

                <Link href="/vitality" className="group relative w-24 h-24 flex flex-col items-center justify-center gap-1.5 rounded-2xl border transition-all duration-300 overflow-hidden select-none"
                  style={{background:"linear-gradient(135deg,rgba(234,179,8,0.12) 0%,rgba(202,138,4,0.05) 100%)",borderColor:"rgba(234,179,8,0.35)",boxShadow:"0 0 20px rgba(234,179,8,0.1),inset 0 1px 0 rgba(234,179,8,0.2)"}}>
                  <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" style={{background:"linear-gradient(135deg,rgba(234,179,8,0.2) 0%,rgba(234,179,8,0.08) 100%)"}}/>
                  <div className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity" style={{background:"linear-gradient(90deg,transparent,rgba(234,179,8,1),transparent)"}}/>
                  <div className="absolute top-1.5 left-1.5 w-1.5 h-1.5 border-t border-l border-yellow-400/50"/><div className="absolute bottom-1.5 right-1.5 w-1.5 h-1.5 border-b border-r border-yellow-400/50"/>
                  <svg className="relative z-10 w-9 h-9" viewBox="0 0 64 64" fill="none">
                    <circle cx="32" cy="36" r="22" fill="rgba(234,179,8,0.15)" stroke="rgba(234,179,8,0.6)" strokeWidth="2"/>
                    <circle cx="32" cy="36" r="15" fill="rgba(234,179,8,0.25)"/>
                    <text x="32" y="43" textAnchor="middle" fontSize="20" fontWeight="bold" fill="rgba(234,179,8,0.9)">$</text>
                    <rect x="24" y="8" width="16" height="12" rx="4" fill="rgba(234,179,8,0.5)" stroke="rgba(234,179,8,0.7)" strokeWidth="1.5"/>
                    <path d="M28 8 Q32 4 36 8" stroke="rgba(234,179,8,0.7)" strokeWidth="1.5" fill="none"/>
                  </svg>
                  <span className="relative z-10 text-[8px] font-mono font-black tracking-widest uppercase text-yellow-400">BUDGET</span>
                </Link>
              </div>

              {/* CENTRE : ECHO */}
              <div className={`relative shrink-0 flex flex-col items-center ${echoState==="idle"?"echo-idle":echoState==="thinking"?"echo-thinking":"echo-speaking"}`}>
                <div className="relative w-24 h-24 flex items-center justify-center">
                  <div className="absolute inset-0 rounded-full" style={{background:"conic-gradient(from 0deg, transparent 50%, rgba(6,182,212,0.3) 80%, #06b6d4 100%)", animation:"spinDash 4s linear infinite"}}/>
                  <div className="absolute inset-1.5 rounded-full bg-black/80"/>
                  <img src="/Echo.png" alt="Echo" className="relative z-10 w-20 h-20 object-cover rounded-full border border-cyan-500/30 shadow-lg"/>
                </div>
                <span className="text-zinc-600 text-[8px] mt-1 tracking-widest uppercase font-mono">{echoState}</span>
              </div>

              {/* DROITE : CALORIES + LIVRE */}
              <div className="flex gap-3 shrink-0">
                <Link href="/vitality" className="group relative w-24 h-24 flex flex-col items-center justify-center gap-1.5 rounded-2xl border transition-all duration-300 overflow-hidden select-none"
                  style={{background:"linear-gradient(135deg,rgba(34,197,94,0.12) 0%,rgba(22,163,74,0.05) 100%)",borderColor:"rgba(34,197,94,0.35)",boxShadow:"0 0 20px rgba(34,197,94,0.1),inset 0 1px 0 rgba(34,197,94,0.2)"}}>
                  <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" style={{background:"linear-gradient(135deg,rgba(34,197,94,0.2) 0%,rgba(34,197,94,0.08) 100%)"}}/>
                  <div className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity" style={{background:"linear-gradient(90deg,transparent,rgba(34,197,94,1),transparent)"}}/>
                  <div className="absolute top-1.5 left-1.5 w-1.5 h-1.5 border-t border-l border-green-400/50"/><div className="absolute bottom-1.5 right-1.5 w-1.5 h-1.5 border-b border-r border-green-400/50"/>
                  <svg className="relative z-10 w-9 h-9" viewBox="0 0 64 64" fill="none">
                    <ellipse cx="32" cy="38" rx="18" ry="16" fill="rgba(34,197,94,0.2)" stroke="rgba(34,197,94,0.6)" strokeWidth="2"/>
                    <ellipse cx="32" cy="38" rx="12" ry="10" fill="rgba(34,197,94,0.35)"/>
                    <path d="M32 22 Q36 14 44 12 Q38 18 32 22Z" fill="rgba(34,197,94,0.8)"/>
                    <path d="M32 22 Q28 14 20 12 Q26 18 32 22Z" fill="rgba(34,197,94,0.6)"/>
                    <path d="M32 22 L32 30" stroke="rgba(34,197,94,0.7)" strokeWidth="2"/>
                  </svg>
                  <span className="relative z-10 text-[8px] font-mono font-black tracking-widest uppercase text-green-400">CALORIES</span>
                </Link>

                <Link href="/books" className="group relative w-24 h-24 flex flex-col items-center justify-center gap-1.5 rounded-2xl border transition-all duration-300 overflow-hidden select-none"
                  style={{background:"linear-gradient(135deg,rgba(139,92,246,0.12) 0%,rgba(109,40,217,0.05) 100%)",borderColor:"rgba(139,92,246,0.35)",boxShadow:"0 0 20px rgba(139,92,246,0.1),inset 0 1px 0 rgba(139,92,246,0.2)"}}>
                  <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" style={{background:"linear-gradient(135deg,rgba(139,92,246,0.2) 0%,rgba(139,92,246,0.08) 100%)"}}/>
                  <div className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity" style={{background:"linear-gradient(90deg,transparent,rgba(139,92,246,1),transparent)"}}/>
                  <div className="absolute top-1.5 left-1.5 w-1.5 h-1.5 border-t border-l border-violet-400/50"/><div className="absolute bottom-1.5 right-1.5 w-1.5 h-1.5 border-b border-r border-violet-400/50"/>
                  <svg className="relative z-10 w-9 h-9" viewBox="0 0 64 64" fill="none">
                    <rect x="8"  y="12" width="20" height="40" rx="3" fill="rgba(139,92,246,0.5)" stroke="rgba(139,92,246,0.7)" strokeWidth="1.5"/>
                    <rect x="10" y="14" width="16" height="36" rx="2" fill="rgba(139,92,246,0.2)"/>
                    <rect x="30" y="10" width="20" height="42" rx="3" fill="rgba(168,85,247,0.5)" stroke="rgba(168,85,247,0.7)" strokeWidth="1.5"/>
                    <rect x="32" y="12" width="16" height="38" rx="2" fill="rgba(168,85,247,0.2)"/>
                    <line x1="13" y1="20" x2="23" y2="20" stroke="rgba(255,255,255,0.3)" strokeWidth="1.2"/>
                    <line x1="13" y1="25" x2="23" y2="25" stroke="rgba(255,255,255,0.3)" strokeWidth="1.2"/>
                    <line x1="33" y1="18" x2="47" y2="18" stroke="rgba(255,255,255,0.3)" strokeWidth="1.2"/>
                    <line x1="33" y1="23" x2="47" y2="23" stroke="rgba(255,255,255,0.3)" strokeWidth="1.2"/>
                  </svg>
                  <span className="relative z-10 text-[8px] font-mono font-black tracking-widest uppercase text-violet-400">{lang==="fr"?"LIVRE":"BOOK"}</span>
                </Link>
              </div>

            </div>
            <style>{`@keyframes spinDash { 100% { transform: rotate(360deg); } }`}</style>

            {/* MESSAGES */}
            <div className="flex-1 overflow-y-auto overflow-x-hidden min-h-0 mt-2 px-2">
              {messages.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center">
                  {!tutorialStep && (
                    <div className="hidden">

                      {/* GAUCHE : CALENDRIER + BUDGET */}
                      <div className="flex flex-col gap-3 shrink-0">
                        {/* CALENDRIER */}
                        <Link href="/calendar" className="group relative w-32 h-32 xl:w-36 xl:h-36 flex flex-col items-center justify-center gap-2 rounded-2xl border transition-all duration-300 overflow-hidden select-none"
                          style={{background:"linear-gradient(135deg,rgba(59,130,246,0.12) 0%,rgba(37,99,235,0.05) 100%)",borderColor:"rgba(59,130,246,0.35)",boxShadow:"0 0 24px rgba(59,130,246,0.1),inset 0 1px 0 rgba(59,130,246,0.2)"}}>
                          <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" style={{background:"linear-gradient(135deg,rgba(59,130,246,0.2) 0%,rgba(59,130,246,0.08) 100%)",boxShadow:"inset 0 0 28px rgba(59,130,246,0.25)"}}/>
                          <div className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity" style={{background:"linear-gradient(90deg,transparent,rgba(59,130,246,1),transparent)"}}/>
                          <div className="absolute top-2 left-2 w-2 h-2 border-t border-l border-blue-400/50"/><div className="absolute bottom-2 right-2 w-2 h-2 border-b border-r border-blue-400/50"/>
                          <svg className="relative z-10 w-12 h-12 xl:w-14 xl:h-14" viewBox="0 0 64 64" fill="none">
                            <rect x="6" y="10" width="52" height="48" rx="8" fill="rgba(59,130,246,0.15)" stroke="rgba(59,130,246,0.6)" strokeWidth="2"/>
                            <rect x="6" y="10" width="52" height="16" rx="8" fill="rgba(59,130,246,0.4)"/>
                            <rect x="6" y="18" width="52" height="8" fill="rgba(59,130,246,0.4)"/>
                            <circle cx="20" cy="8" r="4" fill="rgba(59,130,246,0.8)"/>
                            <circle cx="44" cy="8" r="4" fill="rgba(59,130,246,0.8)"/>
                            <rect x="14" y="34" width="8" height="8" rx="2" fill="rgba(59,130,246,0.7)"/>
                            <rect x="28" y="34" width="8" height="8" rx="2" fill="rgba(59,130,246,0.5)"/>
                            <rect x="42" y="34" width="8" height="8" rx="2" fill="rgba(59,130,246,0.5)"/>
                            <rect x="14" y="46" width="8" height="6" rx="2" fill="rgba(59,130,246,0.4)"/>
                            <rect x="28" y="46" width="8" height="6" rx="2" fill="rgba(59,130,246,0.4)"/>
                          </svg>
                          <span className="relative z-10 text-[10px] xl:text-[11px] font-mono font-black tracking-widest uppercase text-blue-400 group-hover:text-blue-300 transition-colors">
                            {lang==="fr"?"CALENDRIER":"CALENDAR"}
                          </span>
                        </Link>

                        {/* BUDGET */}
                        <Link href="/vitality" className="group relative w-32 h-32 xl:w-36 xl:h-36 flex flex-col items-center justify-center gap-2 rounded-2xl border transition-all duration-300 overflow-hidden select-none"
                          style={{background:"linear-gradient(135deg,rgba(234,179,8,0.12) 0%,rgba(202,138,4,0.05) 100%)",borderColor:"rgba(234,179,8,0.35)",boxShadow:"0 0 24px rgba(234,179,8,0.1),inset 0 1px 0 rgba(234,179,8,0.2)"}}>
                          <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" style={{background:"linear-gradient(135deg,rgba(234,179,8,0.2) 0%,rgba(234,179,8,0.08) 100%)",boxShadow:"inset 0 0 28px rgba(234,179,8,0.25)"}}/>
                          <div className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity" style={{background:"linear-gradient(90deg,transparent,rgba(234,179,8,1),transparent)"}}/>
                          <div className="absolute top-2 left-2 w-2 h-2 border-t border-l border-yellow-400/50"/><div className="absolute bottom-2 right-2 w-2 h-2 border-b border-r border-yellow-400/50"/>
                          <svg className="relative z-10 w-12 h-12 xl:w-14 xl:h-14" viewBox="0 0 64 64" fill="none">
                            <circle cx="32" cy="36" r="22" fill="rgba(234,179,8,0.15)" stroke="rgba(234,179,8,0.6)" strokeWidth="2"/>
                            <circle cx="32" cy="36" r="16" fill="rgba(234,179,8,0.25)"/>
                            <text x="32" y="42" textAnchor="middle" fontSize="20" fontWeight="bold" fill="rgba(234,179,8,0.9)">$</text>
                            <rect x="24" y="8" width="16" height="12" rx="4" fill="rgba(234,179,8,0.5)" stroke="rgba(234,179,8,0.7)" strokeWidth="1.5"/>
                            <path d="M28 8 Q32 4 36 8" stroke="rgba(234,179,8,0.7)" strokeWidth="1.5" fill="none"/>
                          </svg>
                          <span className="relative z-10 text-[10px] xl:text-[11px] font-mono font-black tracking-widest uppercase text-yellow-400 group-hover:text-yellow-300 transition-colors">
                            BUDGET
                          </span>
                        </Link>
                      </div>

                      {/* CENTRE : ECHO */}
                      <div className={`relative shrink-0 flex flex-col items-center ${echoState==="idle"?"echo-idle":echoState==="thinking"?"echo-thinking":"echo-speaking"}`}>
                        <div className="relative w-28 h-28 xl:w-32 xl:h-32 flex items-center justify-center">
                          {/* Anneau glow */}
                          <div className="absolute inset-0 rounded-full" style={{background:"conic-gradient(from 0deg, transparent 50%, rgba(6,182,212,0.3) 80%, #06b6d4 100%)", animation:"spin 4s linear infinite"}}/>
                          <div className="absolute inset-1.5 rounded-full bg-black/80"/>
                          <img src="/Echo.png" alt="Echo Core" className="relative z-10 w-24 h-24 xl:w-28 xl:h-28 object-cover rounded-full border border-cyan-500/30 shadow-lg"/>
                        </div>
                        <span className="text-zinc-500 dark:text-zinc-600 text-[9px] block mt-2 tracking-widest uppercase font-mono">{echoState}</span>
                        <style>{`@keyframes spin { 100% { transform: rotate(360deg); } }`}</style>
                      </div>

                      {/* DROITE : CALORIES + LIVRE */}
                      <div className="flex flex-col gap-3 shrink-0">
                        {/* CALORIES */}
                        <Link href="/vitality" className="group relative w-32 h-32 xl:w-36 xl:h-36 flex flex-col items-center justify-center gap-2 rounded-2xl border transition-all duration-300 overflow-hidden select-none"
                          style={{background:"linear-gradient(135deg,rgba(34,197,94,0.12) 0%,rgba(22,163,74,0.05) 100%)",borderColor:"rgba(34,197,94,0.35)",boxShadow:"0 0 24px rgba(34,197,94,0.1),inset 0 1px 0 rgba(34,197,94,0.2)"}}>
                          <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" style={{background:"linear-gradient(135deg,rgba(34,197,94,0.2) 0%,rgba(34,197,94,0.08) 100%)",boxShadow:"inset 0 0 28px rgba(34,197,94,0.25)"}}/>
                          <div className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity" style={{background:"linear-gradient(90deg,transparent,rgba(34,197,94,1),transparent)"}}/>
                          <div className="absolute top-2 left-2 w-2 h-2 border-t border-l border-green-400/50"/><div className="absolute bottom-2 right-2 w-2 h-2 border-b border-r border-green-400/50"/>
                          <svg className="relative z-10 w-12 h-12 xl:w-14 xl:h-14" viewBox="0 0 64 64" fill="none">
                            <ellipse cx="32" cy="38" rx="18" ry="16" fill="rgba(34,197,94,0.2)" stroke="rgba(34,197,94,0.6)" strokeWidth="2"/>
                            <ellipse cx="32" cy="38" rx="13" ry="11" fill="rgba(34,197,94,0.35)"/>
                            <path d="M32 22 Q36 14 44 12 Q38 18 32 22Z" fill="rgba(34,197,94,0.8)"/>
                            <path d="M32 22 Q28 14 20 12 Q26 18 32 22Z" fill="rgba(34,197,94,0.6)"/>
                            <path d="M32 22 L32 30" stroke="rgba(34,197,94,0.7)" strokeWidth="2"/>
                          </svg>
                          <span className="relative z-10 text-[10px] xl:text-[11px] font-mono font-black tracking-widest uppercase text-green-400 group-hover:text-green-300 transition-colors">
                            CALORIES
                          </span>
                        </Link>

                        {/* LIVRE */}
                        <Link href="/books" className="group relative w-32 h-32 xl:w-36 xl:h-36 flex flex-col items-center justify-center gap-2 rounded-2xl border transition-all duration-300 overflow-hidden select-none"
                          style={{background:"linear-gradient(135deg,rgba(139,92,246,0.12) 0%,rgba(109,40,217,0.05) 100%)",borderColor:"rgba(139,92,246,0.35)",boxShadow:"0 0 24px rgba(139,92,246,0.1),inset 0 1px 0 rgba(139,92,246,0.2)"}}>
                          <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" style={{background:"linear-gradient(135deg,rgba(139,92,246,0.2) 0%,rgba(139,92,246,0.08) 100%)",boxShadow:"inset 0 0 28px rgba(139,92,246,0.25)"}}/>
                          <div className="absolute top-0 left-0 right-0 h-px opacity-0 group-hover:opacity-100 transition-opacity" style={{background:"linear-gradient(90deg,transparent,rgba(139,92,246,1),transparent)"}}/>
                          <div className="absolute top-2 left-2 w-2 h-2 border-t border-l border-violet-400/50"/><div className="absolute bottom-2 right-2 w-2 h-2 border-b border-r border-violet-400/50"/>
                          <svg className="relative z-10 w-12 h-12 xl:w-14 xl:h-14" viewBox="0 0 64 64" fill="none">
                            <rect x="8"  y="12" width="20" height="40" rx="3" fill="rgba(139,92,246,0.5)" stroke="rgba(139,92,246,0.7)" strokeWidth="1.5"/>
                            <rect x="10" y="14" width="16" height="36" rx="2" fill="rgba(139,92,246,0.2)"/>
                            <rect x="30" y="10" width="20" height="42" rx="3" fill="rgba(168,85,247,0.5)" stroke="rgba(168,85,247,0.7)" strokeWidth="1.5"/>
                            <rect x="32" y="12" width="16" height="38" rx="2" fill="rgba(168,85,247,0.2)"/>
                            <line x1="13" y1="20" x2="23" y2="20" stroke="rgba(255,255,255,0.3)" strokeWidth="1.2"/>
                            <line x1="13" y1="24" x2="23" y2="24" stroke="rgba(255,255,255,0.3)" strokeWidth="1.2"/>
                            <line x1="13" y1="28" x2="20" y2="28" stroke="rgba(255,255,255,0.2)" strokeWidth="1.2"/>
                            <line x1="33" y1="18" x2="47" y2="18" stroke="rgba(255,255,255,0.3)" strokeWidth="1.2"/>
                            <line x1="33" y1="22" x2="47" y2="22" stroke="rgba(255,255,255,0.3)" strokeWidth="1.2"/>
                            <line x1="33" y1="26" x2="43" y2="26" stroke="rgba(255,255,255,0.2)" strokeWidth="1.2"/>
                          </svg>
                          <span className="relative z-10 text-[10px] xl:text-[11px] font-mono font-black tracking-widest uppercase text-violet-400 group-hover:text-violet-300 transition-colors">
                            {lang==="fr"?"LIVRE":"BOOK"}
                          </span>
                        </Link>
                      </div>

                    </div>
                  )}
                </div>
              ) : (
                <div className="max-w-4xl mx-auto py-4 flex flex-col gap-10 min-w-0">
                  {messages.map((msg, index) => {
                    const isEcho = /^Echo\s*:/i.test(msg.raw);
                    const isUser = /^(You|Toi)\s*:/i.test(msg.raw);
                    const isLastEcho = isEcho && index === lastEchoIndex;
                    const cleanText = msg.raw.replace(/^(Echo|You|Toi)\s*:\s*/i,"");
                    const isDefaultImgText = cleanText === "Analyse cette image." || cleanText === "Analyze this image.";

                    if (isEcho) return (
                      <div key={index} className="flex flex-col gap-4 animate-in fade-in duration-300 min-w-0">
                        <div className="flex items-center gap-4">
                          <img src="/Echo.png" alt="Echo"
                            className={`w-14 h-14 rounded-full object-cover shrink-0 border border-zinc-300 dark:border-zinc-800 shadow-md ${isLastEcho ? echoState==="thinking"?"echo-thinking":echoState==="speaking"?"echo-speaking":"echo-idle":"echo-idle"}`} />
                          <div className="flex flex-col">
                            <span className="text-zinc-500 dark:text-zinc-400 text-xs font-mono uppercase tracking-widest font-bold">Echo</span>
                            <span className="text-zinc-400 dark:text-zinc-600 text-[10px] font-mono">Core Frequency</span>
                          </div>
                        </div>
                        <div className="text-zinc-800 dark:text-zinc-200 text-[15px] leading-8 font-normal tracking-wide selection:bg-cyan-500/30 flex flex-col gap-5 pl-2 sm:pl-18 break-words min-w-0">
                          {cleanText.split(/\n\n+/).map((block, i) => <p key={i} className="whitespace-pre-wrap break-words">{block}</p>)}
                        </div>
                      </div>
                    );

                    if (isUser) return (
                      <div key={index} className="flex flex-col items-end animate-in fade-in duration-200 min-w-0">
                        {msg.imageB64 && <img src={msg.imageB64} alt="image envoyée" className="max-w-[180px] max-h-[140px] rounded-xl border border-zinc-300 dark:border-zinc-700 object-cover shadow-md mb-1" />}
                        {!(msg.imageB64 && isDefaultImgText) && (
                          <div className="max-w-xl text-right">
                            <p className="text-zinc-700 dark:text-zinc-300 text-[14px] leading-7 tracking-wide bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl px-5 py-3 inline-block text-left whitespace-pre-wrap break-words selection:bg-cyan-500/30">{cleanText}</p>
                          </div>
                        )}
                        {msg.imageB64 && isDefaultImgText && <span className="text-zinc-500 dark:text-zinc-600 text-[10px] italic mt-0.5">{lang==="fr"?"Analyse cette image.":"Analyze this image."}</span>}
                      </div>
                    );

                    return <div key={index} className="p-2 break-words text-xs italic text-zinc-400">{msg.raw}</div>;
                  })}
                  <div ref={bottomRef} />
                </div>
              )}
            </div>

            {/* INPUT */}
            <div className="flex flex-col gap-2 mt-4 shrink-0 px-2 min-w-0">
              <div className="max-w-4xl w-full mx-auto flex flex-col gap-2 min-w-0">
                {selectedImage && (
                  <div className="flex items-center justify-between bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1.5 rounded-xl text-[11px] text-emerald-600 dark:text-emerald-400 max-w-full">
                    <div className="flex items-center gap-2 truncate min-w-0">
                      <img src={selectedImage} alt="preview" className="w-8 h-8 rounded object-cover border border-emerald-500/30 shrink-0" />
                      <span className="truncate font-medium">{selectedImageName || (lang==="fr"?"Image prête":"Image ready")}</span>
                    </div>
                    <button onClick={() => { setSelectedImage(null); setSelectedImageName(""); }} className="text-zinc-400 hover:text-red-500 font-bold ml-2 shrink-0">✕</button>
                  </div>
                )}

                <div className="bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-900 rounded-2xl shadow-inner focus-within:border-cyan-500/40 transition-colors overflow-hidden">
                  <textarea ref={textareaRef}
                    className="w-full bg-transparent text-black dark:text-white placeholder-zinc-400 dark:placeholder-zinc-700 text-sm leading-relaxed resize-y min-h-[48px] max-h-[300px] p-4 focus:outline-none break-words whitespace-pre-wrap"
                    style={{ height: inputHeight }}
                    maxLength={getMessageMaxLength(userTier)}
                    value={message}
                    onChange={e => setMessage(e.target.value)}
                    onPaste={handlePaste}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); envoyer(); } }}
                    placeholder={t.chat.placeholder}
                  />
                  <div className="flex items-center justify-between gap-2 px-3 py-2 border-t border-zinc-200 dark:border-zinc-900">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <button type="button" onClick={shrinkInput} title={lang==="fr"?"Réduire":"Shrink"}
                        className="h-8 w-8 shrink-0 rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-500 hover:border-cyan-500/50 hover:text-cyan-600 dark:hover:text-cyan-400 transition-colors flex items-center justify-center text-xs">➖</button>
                      <button type="button" onClick={resetInput} title={lang==="fr"?"Taille originale":"Reset size"}
                        className="h-8 w-8 shrink-0 rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-500 hover:border-cyan-500/50 hover:text-cyan-600 dark:hover:text-cyan-400 transition-colors flex items-center justify-center text-xs">↺</button>
                      <div className="w-px h-5 bg-zinc-200 dark:bg-zinc-800 mx-0.5 shrink-0" />
                      <input ref={imageInputRef} type="file" accept="image/*" onChange={handleImageSelection} className="hidden" />
                      <button type="button" disabled={isImageButtonLocked} onClick={() => imageInputRef.current?.click()}
                        title={isImageButtonLocked ? (lang==="fr"?"Plan Premium requis":"Premium plan required") : (selectedImageName||"")}
                        className={`h-8 px-3 rounded-lg font-bold text-[11px] flex items-center gap-1.5 border transition-all shrink-0 ${
                          isImageButtonLocked ? "cursor-not-allowed bg-zinc-200 dark:bg-zinc-900 border-zinc-300 dark:border-zinc-800 text-zinc-500"
                            : selectedImage ? "bg-emerald-600/15 border-emerald-500/40 text-emerald-600 dark:text-emerald-400"
                            : "bg-violet-600/10 border-violet-500/30 hover:bg-violet-600/20 text-violet-600 dark:text-violet-400"}`}>
                        <span>{isImageButtonLocked?"🔒":selectedImage?"✓":"🖼️"}</span>
                        <span className="truncate hidden sm:inline">{isImageButtonLocked?"🔒":selectedImage?(lang==="fr"?"Image prête":"Image Ready"):(lang==="fr"?"Analyse d'image":"Image Analysis")}</span>
                      </button>
                      <button onClick={lancerDictation}
                        className={`h-8 px-3 rounded-lg font-bold text-[11px] flex items-center gap-1.5 border transition-all shrink-0 ${isListening?"bg-red-600 border-red-500 animate-pulse text-white":"bg-cyan-600/10 border-cyan-500/30 hover:bg-cyan-600/20 text-cyan-600 dark:text-cyan-400"}`}>
                        <span>{isListening?"🔴":"🎤"}</span>
                        <span className="hidden sm:inline">{isListening?"Stop":(lang==="fr"?"Parler":"Speak")}</span>
                      </button>
                    </div>
                    <button onClick={envoyer} className="h-8 px-5 bg-cyan-600 hover:bg-cyan-500 rounded-lg font-bold text-[11px] text-white transition-all shadow-md uppercase tracking-wider shrink-0">
                      {t.chat.send}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <div onMouseDown={startPanelResize("right")} className="hidden lg:flex w-2.5 shrink-0 cursor-col-resize items-center justify-center group">
            <div className="w-1 h-12 rounded-full bg-zinc-200 dark:bg-zinc-800 group-hover:bg-cyan-500 transition-colors" />
          </div>

          {/* HUB */}
          <aside style={isDesktop ? { width: rightPanelWidth, flexBasis: rightPanelWidth } : undefined}
            className="w-full lg:w-64 shrink-0 border-t lg:border-t-0 lg:border-l border-zinc-200 dark:border-zinc-800 p-3 flex flex-col bg-zinc-50 dark:bg-zinc-950 max-h-[50vh] lg:max-h-none overflow-y-auto lg:overflow-visible">

            <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0" onClick={e => e.stopPropagation()}>
              <span className="text-[10px] uppercase font-mono tracking-widest text-zinc-400 dark:text-zinc-500 font-bold">Hub</span>
              <div className="flex items-center gap-2">
                <LangDropdown />
                <button onClick={toggleTheme} className="p-1.5 rounded-lg bg-zinc-100/80 dark:bg-zinc-900/80 border border-zinc-300 dark:border-zinc-700 text-zinc-500 hover:text-cyan-500 hover:border-cyan-500/50 transition-all text-xs">
                  {theme === "dark" ? "☀️" : "🌙"}
                </button>
              </div>

              {tutorialStep === 2 && (
                <div className="absolute right-4 top-16 w-72 bg-zinc-950 text-white dark:bg-white dark:text-black rounded-2xl p-5 shadow-[0_0_30px_rgba(6,182,212,0.5)] border-2 border-cyan-400 dark:border-cyan-500 animate-in zoom-in-95 duration-300 z-50">
                  <button type="button" onClick={() => { setTutorialStep(null); localStorage.setItem("echo-tuto-done-v1","true"); }}
                    className="absolute top-3 right-3 w-7 h-7 rounded-lg bg-white/10 dark:bg-black/10 hover:bg-red-600 hover:text-white text-white dark:text-black text-xs font-bold flex items-center justify-center transition-colors">✕</button>
                  <h4 className="font-extrabold text-xs sm:text-sm font-mono uppercase tracking-wider text-cyan-500 dark:text-cyan-600 mb-2 pr-8">
                    🤖 {lang==="fr"?"PARAMÈTRES GLOBAUX":"GLOBAL SETTINGS"} (2/2)
                  </h4>
                  <p className="text-xs sm:text-sm text-zinc-200 dark:text-zinc-800 leading-relaxed mb-4 font-semibold">
                    {t.tutorial?.text2 || "Cliquez ici sur l'icône de Paramètres pour ajuster la langue, alterner entre le mode clair et sombre, ou relancer ce guide à tout moment !"}
                  </p>
                  <button onClick={() => { setTutorialStep(null); localStorage.setItem("echo-tuto-done-v1","true"); }}
                    className="w-full py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-extrabold text-xs transition-colors shadow-md uppercase tracking-wider">
                    {t.tutorial?.finish || "C'est parti ! 🚀"}
                  </button>
                </div>
              )}
            </div>

            <div className="flex flex-col sm:flex-row lg:flex-col flex-1 overflow-y-auto lg:overflow-visible min-h-0">

              {/* UPCOMING EVENTS */}
              <div className="flex-1 p-3 border-b sm:border-b-0 sm:border-r lg:border-r-0 lg:border-b border-zinc-200 dark:border-zinc-800 flex flex-col overflow-hidden min-h-0">
                <h2 className="font-bold text-xs mb-2 shrink-0">📅 {lang==="fr"?"Événements à venir":"Upcoming Events"}</h2>
                <div className="flex flex-col gap-1.5 overflow-y-auto flex-1 max-h-36 sm:max-h-none">
                  {upcomingEvents.length === 0 ? (
                    <div className="p-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 text-xs flex items-center gap-2 text-zinc-500">
                      <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />{lang==="fr"?"Aucun événement":"No upcoming events"}
                    </div>
                  ) : (
                    upcomingEvents.map((ev,i) => (
                      <Link key={ev.id+ev.dateKey} href="/calendar" className="p-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 hover:border-cyan-500 transition-all cursor-pointer block text-xs group">
                        <div className="flex items-center gap-2 font-semibold text-cyan-600 dark:text-cyan-400 mb-0.5 group-hover:text-cyan-500">
                          <span className={`w-2 h-2 rounded-full shrink-0 ${EVENT_DOT_COLORS[i%EVENT_DOT_COLORS.length]}`} />{ev.title}
                        </div>
                        <div className="text-zinc-500 dark:text-zinc-400 text-[11px]">{diffDaysLabel(ev.diffDays)} · {ev.dateKey}</div>
                      </Link>
                    ))
                  )}
                </div>
              </div>

              {/* STICKIES */}
              <div className="flex-1 p-3 flex flex-col overflow-hidden min-h-0">
                <h2 className="font-bold text-xs mb-2 shrink-0">🟨 {lang==="fr"?"Notes":"Sticky Notes"}</h2>
                <div className="flex gap-2 mb-2 shrink-0">
                  {(["yellow","blue","green","pink"] as StickyNote["color"][]).map(color => (
                    <button key={color} onClick={() => setSelectedColor(color)}
                      className={`w-5 h-5 rounded-full border-2 transition-all ${STICKY_STYLES[color].dot} ${selectedColor===color?"border-black dark:border-white scale-110":"border-transparent opacity-50"}`} />
                  ))}
                </div>
                <div className="flex gap-2 mb-2 shrink-0">
                  <textarea value={newStickyText} onChange={e => setNewStickyText(e.target.value)}
                    onKeyDown={e => { if (e.key==="Enter"&&!e.shiftKey) { e.preventDefault(); addSticky(); } }}
                    placeholder={lang==="fr"?"Note rapide...":"Quick note..."} rows={2}
                    className={`flex-1 resize-none rounded-lg border p-1.5 text-xs bg-transparent focus:outline-none ${STICKY_STYLES[selectedColor].border} ${STICKY_STYLES[selectedColor].text}`} />
                  <button onClick={addSticky} className="bg-cyan-600 hover:bg-cyan-500 text-white px-2.5 rounded-lg text-xs font-bold">+ {lang==="fr"?"Ajouter":"Add"}</button>
                </div>
                <div className="flex flex-col gap-1.5 overflow-y-auto flex-1 max-h-36 sm:max-h-none">
                  {stickies.map(sticky => {
                    const s = STICKY_STYLES[sticky.color];
                    return (
                      <div key={sticky.id} onDoubleClick={() => { setExpandedSticky(sticky); setEditText(sticky.text); }}
                        className={`relative rounded-lg border p-2 text-xs cursor-pointer group transition-transform hover:scale-102 ${s.bg} ${s.border} ${s.text}`}>
                        <div className="whitespace-pre-wrap line-clamp-3">{sticky.text}</div>
                        <button onClick={e => { e.stopPropagation(); deleteSticky(sticky.id); }} className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-zinc-500 dark:text-white text-xs">✕</button>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </aside>
        </div>
      </div>

      {/* EXPANDED STICKY MODAL */}
      {expandedSticky && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center z-50 p-4" onClick={() => setExpandedSticky(null)}>
          <div className={`max-w-md w-full rounded-2xl p-6 shadow-2xl border ${STICKY_STYLES[expandedSticky.color].bg} ${STICKY_STYLES[expandedSticky.color].border} ${STICKY_STYLES[expandedSticky.color].text}`} onClick={e => e.stopPropagation()}>
            <textarea value={editText} onChange={e => setEditText(e.target.value)} rows={6} className="w-full bg-transparent resize-none focus:outline-none text-sm" autoFocus />
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setExpandedSticky(null)} className="px-3 py-1.5 text-xs rounded-lg border border-current opacity-70 hover:opacity-100">{lang==="fr"?"Annuler":"Cancel"}</button>
              <button onClick={saveStickyEdit} className="px-3 py-1.5 text-xs rounded-lg bg-cyan-600 text-white font-bold">{lang==="fr"?"Sauvegarder":"Save"}</button>
            </div>
          </div>
        </div>
      )}

      {/* LIMIT MODAL */}
      {showLimitModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center z-50 p-4" onClick={() => setShowLimitModal(false)}>
          <div className="bg-white dark:bg-zinc-950 border border-zinc-300 dark:border-zinc-700 p-8 rounded-2xl max-w-md w-full text-center shadow-2xl" onClick={e => e.stopPropagation()}>
            <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-2 capitalize">{activeLimitCategory} Limit</h3>
            <p className="text-zinc-600 dark:text-zinc-400 text-sm mb-6">
              {lang==="fr"
                ? `Limite d'actions automatisées atteinte pour [${activeLimitCategory}]. Passez au plan supérieur pour continuer.`
                : `Automated action limit reached for [${activeLimitCategory}]. Upgrade to continue.`}
            </p>
            <button onClick={() => setShowLimitModal(false)} className="w-full bg-cyan-600 text-white py-2.5 rounded-xl text-xs font-semibold">OK</button>
          </div>
        </div>
      )}
    </main>
  );
}