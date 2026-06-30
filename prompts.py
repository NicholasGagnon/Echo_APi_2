"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { supabase } from "../lib/supabase";
import { checkQuota, getMessageMaxLength, UserTier } from "../../utils/quota";
import TutorialHeaderControls from "../components/TutorialHeaderControls";
import PremiumRequiredModal from "../components/PremiumRequiredModal";
import { useApp } from "../../context/AppContext";

type BudgetExpense  = { id: string; title: string; amount: number; currency: "$"|"US$"|"€"; date: string };
type CalorieLog     = { id: string; foodName: string; calories: number; date: string };
type VitalityMessage = { raw: string; imageB64?: string };

// ── POPUP QUOTA ───────────────────────────────────────────────────────────────
function QuotaPopup({ label, lang, onClose }: { label: string; lang: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/90 backdrop-blur-md flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-950 border-2 border-red-500/40 p-6 rounded-2xl max-w-md w-full relative shadow-[0_0_50px_rgba(239,68,68,0.15)]">
        <button onClick={onClose} className="absolute top-4 right-4 text-zinc-500 hover:text-white font-bold font-mono text-lg">✕</button>
        <div className="flex items-center gap-3 mb-4">
          <span className="text-2xl">⚠️</span>
          <h3 className="text-sm font-mono uppercase tracking-widest text-red-400 font-bold">
            {lang === "fr" ? "Limite atteinte" : "Limit reached"}
          </h3>
        </div>
        <p className="text-zinc-300 text-sm font-mono leading-relaxed mb-1">
          {lang === "fr"
            ? `Vous avez atteint la limite ${label} de votre plan.`
            : `You've reached the ${label} limit of your plan.`}
        </p>
        <p className="text-zinc-500 text-xs font-mono mb-6">
          {lang === "fr"
            ? "Revenez dans 1 heure pour récupérer un crédit ou passez à un plan supérieur."
            : "Come back in 1 hour to recover a credit or upgrade your plan."}
        </p>
        <div className="flex gap-3">
          <Link href="/services"
            className="flex-1 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-black text-xs font-mono uppercase tracking-widest text-center transition-all"
            onClick={onClose}>
            {lang === "fr" ? "Voir les plans" : "View plans"}
          </Link>
          <button onClick={onClose}
            className="px-4 py-2.5 rounded-xl border border-zinc-800 text-zinc-400 hover:text-white text-xs font-mono uppercase tracking-widest transition-all">
            {lang === "fr" ? "Fermer" : "Close"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function VitalityPage() {
  const { t, lang, theme, userTier } = useApp();
  const [isLoaded, setIsLoaded] = useState(false);
  const [userId,   setUserId]   = useState<string | null>(null);
  const [inputEcho,    setInputEcho]    = useState("");
  const [echoMessages, setEchoMessages] = useState<VitalityMessage[]>([]);
  const [memorySummary, setMemorySummary] = useState("");
  const bottomRef  = useRef<HTMLDivElement>(null);
  const [echoState, setEchoState] = useState("idle");

  // ── POPUP CONNEXION / QUOTA ────────────────────────────────────────────────
  const [showLoginPopup,  setShowLoginPopup]  = useState(false);
  const [showQuotaPopup,  setShowQuotaPopup]  = useState(false);
  const [quotaPopupLabel, setQuotaPopupLabel] = useState("");
  const triggerQuotaPopup = (label: string) => { setQuotaPopupLabel(label); setShowQuotaPopup(true); };

  const [isListening, setIsListening] = useState(false);
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [imageName,   setImageName]   = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showPremiumModal, setShowPremiumModal] = useState(false);
  const [tutorialStep, setTutorialStep] = useState<number | null>(null);

  const [expenses,     setExpenses]     = useState<BudgetExpense[]>([]);
  const [caloriesList, setCaloriesList] = useState<CalorieLog[]>([]);

  const [manualExpenseTitle,    setManualExpenseTitle]    = useState("");
  const [manualExpenseAmount,   setManualExpenseAmount]   = useState("");
  const [manualExpenseCurrency, setManualExpenseCurrency] = useState<"$"|"US$"|"€">("$");
  const [manualExpenseDate,     setManualExpenseDate]     = useState(new Date().toLocaleDateString("fr-CA"));
  const [manualFoodName, setManualFoodName] = useState("");
  const [manualCalories, setManualCalories] = useState("");

  const [budgetGoal,      setBudgetGoal]      = useState(3000);
  const [calorieGoal,     setCalorieGoal]     = useState(2300);
  const [isEditingBudget,   setIsEditingBudget]   = useState(false);
  const [isEditingCalories, setIsEditingCalories] = useState(false);
  const [inputBudgetGoal,   setInputBudgetGoal]  = useState("3000");
  const [inputCalorieGoal, setInputCalorieGoal] = useState("2300");
  const [userWeight, setUserWeight] = useState("");
  const [userHeight, setUserHeight] = useState("");

  const [showProfileModal,  setShowProfileModal]  = useState(false);
  const [weightUnit,        setWeightUnit]        = useState<"kg"|"lbs">("kg");
  const [heightUnit,        setHeightUnit]        = useState<"cm"|"ft">("cm");
  const [modalWeight,       setModalWeight]       = useState("");
  const [modalHeight,       setModalHeight]       = useState("");
  const [modalHeightInches, setModalHeightInches] = useState("");
  const [modalAge,    setModalAge]    = useState("30");
  const [modalGender, setModalGender] = useState("homme");

  const safeTier = (userTier || "connected_free") as UserTier;
  const isImageButtonLocked = safeTier === "connected_free" || safeTier === "basic";

  const dict = {
    fr: {
      title:"Configuration Metabolique", desc:"Entrez vos donnees de base ici. Echo analysera vos besoins energetiques et orchestrera votre strategie de deficit calorique.",
      weight:"Poids", height:"Taille", age:"Age", gender:"Sexe biologique", male:"Homme", female:"Femme",
      btnApply:"Appliquer et Synchroniser Echo", btnCalc:"Calculer mon Deficit",
      spent:"Depense", remaining:"Restant", goal:"Objectif",
      fluxFin:"FINANCIAL FLOW", regVit:"VITALITY LOG", ctrlTitle:"ECHO VITALITY CONTROLLER",
      noTrans:"Aucune transaction enregistree.", noMeal:"Aucun repas enregistre.",
      placeholder:"Rentre une transaction ou un repas (ex: Pizza 600 kcal)...",
    },
    en: {
      title:"Metabolic Configuration", desc:"Enter your primary body data here. Echo will analyze your energy needs and personalize your calorie target.",
      weight:"Weight", height:"Height", age:"Age", gender:"Biological Sex", male:"Male", female:"Female",
      btnApply:"Apply and Sync Echo", btnCalc:"Calculate My Deficit",
      spent:"Spent", remaining:"Remaining", goal:"Goal",
      fluxFin:"FINANCIAL FLOW", regVit:"VITALITY LOG", ctrlTitle:"ECHO VITALITY CONTROLLER",
      noTrans:"No transactions recorded.", noMeal:"No meals logged.",
      placeholder:"Log a transaction or meal (e.g. Pizza 600 kcal)...",
    },
  }[lang === "fr" ? "fr" : "en"];

  const getBudgetGoalKey      = (uid: string|null) => uid ? `echo-budget-goal-${uid}`           : "echo-budget-goal";
  const getCalorieGoalKey     = (uid: string|null) => uid ? `echo-calorie-goal-${uid}`          : "echo-calorie-goal";
  const getVitalityProfileKey = (uid: string|null) => uid ? `echo-vitality-profile-${uid}`      : "echo-vitality-profile";
  const getVitalityConvoKey   = (uid: string|null) => uid ? `echo-vitality-conversation-${uid}` : "echo-vitality-conversation";
  const getVitalitySummaryKey = (uid: string|null) => uid ? `echo-vitality-summary-${uid}`      : "echo-vitality-summary";

  const lastEchoIndex   = echoMessages.findLastIndex(m => /^Echo\s*:/i.test(m.raw));
  const serializeMsgs   = (msgs: VitalityMessage[]) => msgs.map(m => m.raw);
  const deserializeMsgs = (raws: string[]): VitalityMessage[] => raws.map(r => ({ raw: r }));

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      const uid = session?.user?.id || null;
      setUserId(uid);
      try {
        if (uid) {
          const { data: expRows } = await supabase.from("echo_expenses").select("*").eq("user_id", uid).order("date", { ascending: false });
          setExpenses((expRows||[]).map(r => ({ id: r.id, title: r.title, amount: r.amount, currency: (r.currency||"$") as "$"|"US$"|"€", date: r.date })));
          const { data: calRows } = await supabase.from("echo_calories").select("*").eq("user_id", uid).order("date", { ascending: false });
          setCaloriesList((calRows||[]).map(r => ({ id: r.id, foodName: r.food_name, calories: r.calories, date: r.date })));
        }

        const savedConvo    = localStorage.getItem(getVitalityConvoKey(uid));
        const savedSummary  = localStorage.getItem(getVitalitySummaryKey(uid));
        if (savedConvo)   setEchoMessages(deserializeMsgs(JSON.parse(savedConvo)));
        if (savedSummary) setMemorySummary(savedSummary);

        if (!uid) {
          const guestExp = localStorage.getItem("echo-budget-expenses-guest");
          if (guestExp) setExpenses(JSON.parse(guestExp));
          const guestCal = localStorage.getItem("echo-calorie-logs-guest");
          if (guestCal) setCaloriesList(JSON.parse(guestCal));
        }

        const savedBGoal = localStorage.getItem(getBudgetGoalKey(uid)) || localStorage.getItem("echo-budget-goal");
        if (savedBGoal) { setBudgetGoal(Number(savedBGoal)); setInputBudgetGoal(savedBGoal); }
        const savedCGoal = localStorage.getItem(getCalorieGoalKey(uid)) || localStorage.getItem("echo-calorie-goal");
        if (savedCGoal) { setCalorieGoal(Number(savedCGoal)); setInputCalorieGoal(savedCGoal); }

        const savedProfile = localStorage.getItem(getVitalityProfileKey(uid));
        if (savedProfile) {
          const p = JSON.parse(savedProfile);
          setUserWeight(p.weight||""); setUserHeight(p.height||"");
          setModalWeight(p.weight||""); setModalHeight(p.height||"");
        }

        setShowLoginPopup(!uid);
      } catch(e) { console.error("Init error", e); }
      setIsLoaded(true);
    });

    const { data: listener } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (event === "SIGNED_OUT" || !session?.user) {
        setUserId(null); setExpenses([]); setCaloriesList([]); setEchoMessages([]); setMemorySummary(""); return;
      }
      if (event === "SIGNED_IN" || event === "TOKEN_REFRESHED") {
        const uid = session.user.id; setUserId(uid);
        setShowLoginPopup(false);
        const { data: expRows } = await supabase.from("echo_expenses").select("*").eq("user_id", uid).order("date", { ascending: false });
        setExpenses((expRows||[]).map(r => ({ id: r.id, title: r.title, amount: r.amount, currency: (r.currency||"$") as "$"|"€", date: r.date })));
        const { data: calRows } = await supabase.from("echo_calories").select("*").eq("user_id", uid).order("date", { ascending: false });
        setCaloriesList((calRows||[]).map(r => ({ id: r.id, foodName: r.food_name, calories: r.calories, date: r.date })));
        const convo   = localStorage.getItem(getVitalityConvoKey(uid));
        const summary = localStorage.getItem(getVitalitySummaryKey(uid));
        setEchoMessages(convo ? deserializeMsgs(JSON.parse(convo)) : []);
        setMemorySummary(summary || "");
        const bGoal = localStorage.getItem(getBudgetGoalKey(uid));
        if (bGoal) { setBudgetGoal(Number(bGoal)); setInputBudgetGoal(bGoal); }
        const cGoal = localStorage.getItem(getCalorieGoalKey(uid));
        if (cGoal) { setCalorieGoal(Number(cGoal)); setInputCalorieGoal(cGoal); }
        const profile = JSON.parse(localStorage.getItem(getVitalityProfileKey(uid))||"{}");
        setUserWeight(profile.weight||""); setUserHeight(profile.height||"");
        setModalWeight(profile.weight||""); setModalHeight(profile.height||"");
      }
    });
    return () => listener.subscription.unsubscribe();
  }, []);

  useEffect(() => { if (!isLoaded) return; localStorage.setItem(getBudgetGoalKey(userId), budgetGoal.toString()); }, [budgetGoal, isLoaded, userId]);
  useEffect(() => { if (!isLoaded) return; localStorage.setItem(getCalorieGoalKey(userId), calorieGoal.toString()); }, [calorieGoal, isLoaded, userId]);
  useEffect(() => { if (!isLoaded) return; localStorage.setItem(getVitalityProfileKey(userId), JSON.stringify({ weight: userWeight, height: userHeight })); }, [userWeight, userHeight, isLoaded, userId]);
  useEffect(() => {
    if (!isLoaded) return;
    localStorage.setItem(getVitalityConvoKey(userId), JSON.stringify(serializeMsgs(echoMessages)));
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [echoMessages, isLoaded, userId]);

  const totalSpentUSD      = expenses.filter(i => i.currency==="$" || i.currency==="US$").reduce((s,i) => s+i.amount, 0);
  const totalSpentEUR      = expenses.filter(i => i.currency==="€").reduce((s,i) => s+i.amount, 0);
  const totalSpentCombined = totalSpentUSD + totalSpentEUR;
  const budgetPercentage   = Math.min((totalSpentCombined/budgetGoal)*100, 100);
  const totalCaloriesEaten = caloriesList.reduce((s,i) => s+i.calories, 0);
  const calorieRemaining   = Math.max(calorieGoal-totalCaloriesEaten, 0);

  const compressImage = (base64: string): Promise<string> =>
    new Promise(resolve => {
      const img = document.createElement("img");
      img.onload = () => {
        const MAX=1200; let w=img.width, h=img.height;
        if (w>MAX||h>MAX) { if(w>h){h=Math.round(h*MAX/w);w=MAX;}else{w=Math.round(w*MAX/h);h=MAX;} }
        const canvas=document.createElement("canvas"); canvas.width=w; canvas.height=h;
        canvas.getContext("2d")!.drawImage(img,0,0,w,h);
        resolve(canvas.toDataURL("image/jpeg",0.75));
      };
      img.src=base64;
    });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    setImageName(file.name);
    const reader = new FileReader();
    reader.onloadend = async () => { const c = await compressImage(reader.result as string); setImageBase64(c); };
    reader.readAsDataURL(file);
    e.target.value="";
  };

  const LOCAL_EXPENSES = "echo-budget-expenses-guest";
  const LOCAL_CALORIES = "echo-calorie-logs-guest";
  const persistLocalExpenses = (list: BudgetExpense[]) => localStorage.setItem(LOCAL_EXPENSES, JSON.stringify(list));
  const persistLocalCalories = (list: CalorieLog[])    => localStorage.setItem(LOCAL_CALORIES, JSON.stringify(list));

  const addExpense = async (exp: Omit<BudgetExpense,"id">) => {
    if (!userId) {
      const e: BudgetExpense = { id: Date.now().toString(), ...exp };
      setExpenses(prev => { const n=[e,...prev]; persistLocalExpenses(n); return n; }); return;
    }
    const { data, error } = await supabase.from("echo_expenses").insert({
      user_id: userId, title: exp.title, amount: exp.amount, currency: exp.currency, date: exp.date,
    }).select().single();
    if (error) { console.error("[Vitality] add expense:", error.message); return; }
    setExpenses(prev => [{ id: data.id, title: data.title, amount: data.amount, currency: (data.currency||"$") as "$"|"€", date: data.date }, ...prev]);
  };

  const deleteExpense = async (id: string) => {
    if (userId) { await supabase.from("echo_expenses").delete().eq("id",id).eq("user_id",userId); }
    setExpenses(prev => { const n=prev.filter(i=>i.id!==id); if(!userId)persistLocalExpenses(n); return n; });
  };

  const updateExpense = async (id: string, changes: Partial<BudgetExpense>) => {
    if (userId) {
      const db: Record<string,unknown> = {};
      if (changes.title    !== undefined) db.title    = changes.title;
      if (changes.amount   !== undefined) db.amount   = changes.amount;
      if (changes.currency !== undefined) db.currency = changes.currency;
      if (changes.date     !== undefined) db.date     = changes.date;
      await supabase.from("echo_expenses").update(db).eq("id",id).eq("user_id",userId);
    }
    setExpenses(prev => prev.map(e => e.id===id ? {...e,...changes} : e));
  };

  const addCalorie = async (cal: Omit<CalorieLog,"id">) => {
    if (!userId) {
      const c: CalorieLog = { id: Date.now().toString(), ...cal };
      setCaloriesList(prev => { const n=[c,...prev]; persistLocalCalories(n); return n; }); return;
    }
    const { data, error } = await supabase.from("echo_calories").insert({
      user_id: userId, food_name: cal.foodName, calories: cal.calories, date: cal.date,
    }).select().single();
    if (error) { console.error("[Vitality] add calorie:", error.message); return; }
    setCaloriesList(prev => [{ id: data.id, foodName: data.food_name, calories: data.calories, date: data.date }, ...prev]);
  };

  const deleteCalorie = async (id: string) => {
    if (userId) { await supabase.from("echo_calories").delete().eq("id",id).eq("user_id",userId); }
    setCaloriesList(prev => { const n=prev.filter(i=>i.id!==id); if(!userId)persistLocalCalories(n); return n; });
  };

  // ── CRON MEMORY ───────────────────────────────────────────────────────────
  const runMemoryCron = async (raws: string[]): Promise<string> => {
    if (raws.length <= 10) return memorySummary;
    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000";
      const res = await fetch(`${API_URL}/memory-summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ summary: memorySummary, messages: raws.slice(0, 500), userTier: safeTier }),
      });
      const data        = await res.json();
      const newSummary  = data.summary || memorySummary;
      setMemorySummary(newSummary);
      localStorage.setItem(getVitalitySummaryKey(userId), newSummary);
      console.log("[MEMORY Vitality] Résumé mis à jour");
      return newSummary;
    } catch (e) {
      console.error("[MEMORY Vitality]", e);
      return memorySummary;
    }
  };

  // ── SEND ECHO ─────────────────────────────────────────────────────────────
  const handleSendEcho = async (forcedText?: string) => {
    if (echoState==="thinking") return;
    const textToSubmit = forcedText ?? inputEcho.trim();
    if (!textToSubmit && !imageBase64) return;

    // ── Quota vitality_actions ────────────────────────────────────────────
    const quotaStatus = checkQuota("vitality_actions", safeTier, true, userId);
    if (!quotaStatus.allowed) {
      triggerQuotaPopup(lang === "fr" ? "Vitalité" : "Vitality");
      return;
    }

    const currentImage = imageBase64;
    const currentName  = imageName;
    const userRaw = forcedText ? `You: ${forcedText}` : textToSubmit
      ? `You: ${textToSubmit}`
      : `You: Analyse cette image${currentName ? ` (${currentName})` : ""}`;

    const userEntry: VitalityMessage = { raw: userRaw, imageB64: currentImage ?? undefined };
    const baseMessages = [...echoMessages, userEntry];

    setEchoState("thinking");
    setEchoMessages([...baseMessages, { raw: "Echo: ..." }]);
    if (!forcedText) setInputEcho("");
    setImageBase64(null); setImageName(null);

    // Cron memory si besoin
    const currentSummary = await runMemoryCron(serializeMsgs(baseMessages));

    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000";
      const response = await fetch(`${API_URL}/vitality`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: textToSubmit || `Analyse cette image${currentName ? ` (${currentName})` : ""}`,
          image: currentImage ?? null,
          history: serializeMsgs(baseMessages),
          summary: currentSummary,
          userTier: safeTier,
          currentExpenses: expenses,
          currentCalories: caloriesList,
          budgetGoal,
          calorieGoal,
          vitalityProfile: { weight: userWeight, height: userHeight },
          source: "vitality",
        }),
      });

      const data = await response.json();
      setEchoState("speaking");

      // ── Quota action automatique ──────────────────────────────────────
      let isActionBlocked = false;
      if (data.action) {
        const actionQuota = checkQuota("vitality_actions", safeTier, true, userId);
        if (!actionQuota.allowed) {
          triggerQuotaPopup(lang === "fr" ? "Vitalité" : "Vitality");
          isActionBlocked = true;
        }
      }

      const actionNotice = isActionBlocked
        ? `\n\n[🔒 ${lang === "fr" ? "Action bloquée — quota Vitalité atteint" : "Action blocked — Vitality quota reached"}]`
        : "";
      
      // On insère le message d'Echo et on en profite pour éliminer les réinjections techniques de l'historique de session
      setEchoMessages(() => {
        const historySansInjection = baseMessages.filter(msg => 
          !msg.raw.includes("[SYNCHRONISATION PROFIL]")
        );
        return [...historySansInjection, { raw: `Echo: ${data.response||""}${actionNotice}` }];
      });

      if (data.action && !isActionBlocked) {
        const { type, payload } = data.action;

        if (type==="ADD_BUDGET_EXPENSE") {
          const rawTitle    = payload.title || payload.name || payload.item || textToSubmit || "Achat";
          const finalTitle  = rawTitle.length > 60 ? rawTitle.slice(0, 60) : rawTitle;
          const finalAmount = parseFloat(payload.amount ?? payload.spent ?? payload.price) || 0;
          const finalDate   = payload.paymentDate || payload.paidAt || payload.date || new Date().toLocaleDateString("fr-CA");
          const detectedCurrency: "$"|"US$"|"€" = payload.currency || (textToSubmit?.toLowerCase().includes("euro") || textToSubmit?.includes("€") ? "€" : "$");
          await addExpense({ title: finalTitle, amount: finalAmount, currency: detectedCurrency, date: finalDate });
        }

        if (type==="UPDATE_BUDGET_EXPENSE") {
          const { id, title, amount, currency, date } = payload;
          await updateExpense(id, { title, amount: amount !== undefined ? parseFloat(amount) : undefined, currency, date });
        }

        if (type==="DELETE_BUDGET_EXPENSE" && payload.id) await deleteExpense(payload.id);

        if (type==="ADD_CALORIE_LOG") {
          const rawFoodName  = payload.foodName || payload.food_name || payload.meal || payload.title || payload.name || textToSubmit || "Aliment";
          const finalFood    = rawFoodName.length > 60 ? rawFoodName.slice(0, 60) : rawFoodName;
          const finalCalories = parseInt(payload.calories ?? payload.kcal) || 0;
          await addCalorie({ foodName: finalFood, calories: finalCalories, date: new Date().toLocaleDateString("fr-CA") });
        }

        if (type==="DELETE_CALORIE_LOG" && payload.id) await deleteCalorie(payload.id);

        if (type==="SET_BUDGET_GOAL" || type==="UPDATE_BUDGET_GOAL") {
          const nextGoal = parseInt(payload.goal ?? payload.budgetGoal ?? payload.amount ?? payload.spent);
          if (Number.isFinite(nextGoal) && nextGoal > 0) { setBudgetGoal(nextGoal); setInputBudgetGoal(nextGoal.toString()); }
        }

        if (type==="SET_CALORIE_GOAL" || type==="UPDATE_CALORIE_GOAL") {
          const nextGoal = parseInt(payload.goal ?? payload.calorieGoal ?? payload.calories);
          if (payload.weight) setUserWeight(String(payload.weight));
          if (payload.height) setUserHeight(String(payload.height));
          if (Number.isFinite(nextGoal) && nextGoal > 0) { setCalorieGoal(nextGoal); setInputCalorieGoal(nextGoal.toString()); }
        }
      }
    } catch {
      setEchoMessages(prev => [...prev.filter(m => m.raw !== "Echo: ..."), { raw: "Echo: Unable to reach backend server." }]);
    }
    setTimeout(() => setEchoState("idle"), 10000);
  };

  const handleSubmitModalProfile = (e: React.FormEvent) => {
    e.preventDefault();
    let weightInKg = parseFloat(modalWeight);
    if (weightUnit==="lbs") weightInKg = weightInKg/2.20462;
    let heightInCm = parseFloat(modalHeight);
    if (heightUnit==="ft") heightInCm = (parseFloat(modalHeight)||0)*30.48 + (parseFloat(modalHeightInches)||0)*2.54;
    const a = parseInt(modalAge);
    if (!weightInKg||!heightInCm||!a) return;
    let bmr = (10*weightInKg)+(6.25*heightInCm)-(5*a);
    bmr = modalGender==="homme" ? bmr+5 : bmr-161;
    const tdee = Math.round(bmr*1.35);
    setUserWeight(String(Math.round(weightInKg)));
    setUserHeight(String(Math.round(heightInCm)));
    setCalorieGoal(tdee); setInputCalorieGoal(String(tdee));
    setShowProfileModal(false);
    handleSendEcho(`[SYNCHRONISATION PROFIL] : Poids: ${Math.round(weightInKg)}kg, Taille: ${Math.round(heightInCm)}cm, Age: ${a}ans, Sexe: ${modalGender}. TDEE estime: ${tdee} kcal. Calcule et recommande mon objectif de deficit calorique optimal.`);
  };

  const handleManualExpenseSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualExpenseTitle.trim()||!manualExpenseAmount) return;
    await addExpense({ title: manualExpenseTitle.trim(), amount: parseFloat(manualExpenseAmount)||0, currency: manualExpenseCurrency, date: manualExpenseDate||new Date().toLocaleDateString("fr-CA") });
    setManualExpenseTitle(""); setManualExpenseAmount("");
  };

  const handleManualCalorieSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualFoodName.trim()||!manualCalories) return;
    await addCalorie({ foodName: manualFoodName.trim(), calories: parseInt(manualCalories)||0, date: new Date().toLocaleDateString("fr-CA") });
    setManualFoodName(""); setManualCalories("");
  };

  const saveBudgetGoal  = () => { setBudgetGoal(parseInt(inputBudgetGoal)||3000);  setIsEditingBudget(false); };
  const saveCalorieGoal = () => { setCalorieGoal(parseInt(inputCalorieGoal)||2300); setIsEditingCalories(false); };

  const lancerDictation = () => {
    const SR = (window as any).SpeechRecognition||(window as any).webkitSpeechRecognition;
    if (!SR) { alert("Speech recognition not supported."); return; }
    const r = new SR();
    r.lang = lang==="fr"?"fr-FR":"en-US";
    r.onstart=()=>setIsListening(true); r.onend=()=>setIsListening(false); r.onerror=()=>setIsListening(false);
    r.onresult=(e:any)=>setInputEcho(p=>p+(p?" ":"")+e.results[0][0].transcript);
    r.start();
  };

  return (
    <main className="vitality-page h-screen w-full bg-white dark:bg-black text-black dark:text-white flex overflow-hidden font-sans relative transition-colors duration-200 selection:bg-cyan-500/30">

      {/* ── POPUP CONNEXION PERSISTANT ──────────── */}
      {showLoginPopup && (
        <div className="fixed inset-0 z-[200] flex items-end justify-center pb-12 sm:items-center sm:pb-0">
          <div className="absolute inset-0 pointer-events-auto" style={{background:"transparent"}} />
          <div className="relative pointer-events-auto bg-zinc-950/95 border border-cyan-500/30 rounded-2xl shadow-[0_0_40px_rgba(6,182,212,0.25)] p-7 w-full max-w-md mx-4 flex flex-col gap-5 animate-in fade-in slide-in-from-bottom-4 duration-300">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-4">
              <div className="flex items-center gap-3">
                <span className="text-2xl">📈</span>
                <h3 className="font-black text-base font-mono uppercase tracking-widest text-cyan-400">
                  {lang === "fr" ? "CONTRÔLEUR VITALITÉ" : "VITALITY CONTROLLER"}
                </h3>
              </div>
            </div>
            <div className="flex gap-4 items-start">
              <div className="shrink-0 bg-zinc-900 p-1.5 rounded-full border border-zinc-800">
                <img src="/echo1.png" alt="Echo" className="w-14 h-14 rounded-full object-cover"/>
              </div>
              <p className="text-zinc-300 text-sm leading-relaxed flex-1 whitespace-pre-line">
                {lang === "fr"
                  ? <>✨ Connecte-toi pour sauvegarder ton budget, tes calories et tes estimations budgétaires. ✨{"\n"}😊</>
                  : <>✨ Log in to save your budget, calories and budget estimates. ✨{"\n"}😊</>}
              </p>
            </div>
            <div className="flex flex-col gap-2 pt-1">
              <a href="https://echosai.ca/account"
                className="w-full text-center py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-extrabold text-sm tracking-widest transition-all shadow-md uppercase block">
                {lang === "fr" ? "SE CONNECTER" : "SIGN IN"}
              </a>
            </div>
          </div>
        </div>
      )}
      {showQuotaPopup && <QuotaPopup label={quotaPopupLabel} lang={lang} onClose={() => setShowQuotaPopup(false)} />}
      {tutorialStep===1 && (
        <div className="absolute top-44 left-6 sm:left-72 w-80 sm:w-[460px] max-h-[85vh] overflow-y-auto bg-zinc-950 text-white dark:bg-white dark:text-black rounded-2xl p-5 shadow-[0_0_30px_rgba(6,182,212,0.6)] border-2 border-cyan-400 dark:border-cyan-500 animate-in fade-in duration-300 z-50">
          <TutorialHeaderControls onClose={()=>{setTutorialStep(null);localStorage.setItem("echo-tuto-vitality-done-v1","true");}} />
          <div className="flex items-center gap-2.5 mb-3 border-b border-zinc-800 dark:border-zinc-200 pb-2 pr-16">
            <span>💸</span>
            <h4 className="font-black text-xs font-mono uppercase tracking-widest text-cyan-400 dark:text-cyan-600">ECHO BUDGET (1/2)</h4>
          </div>
          <div className="text-xs text-zinc-200 dark:text-zinc-800 leading-relaxed font-semibold mb-4 space-y-2">
            {lang==="fr"
              ? <p>Hey! 👋 Je suis aussi la pour garder le controle sur ton budget. Definis ton objectif financier en haut, puis parle-moi dans le chat — je m'occupe du reste. ✨✨✨✨✨✨</p>
              : <p>Hey! 👋 I am here to help you stay on track with finances. Set your goal above, then just tell me what you spent — I will handle the rest. ✨✨✨✨✨</p>}
          </div>
          <div className="flex flex-col gap-2 pt-2 border-t border-zinc-800 dark:border-zinc-200">
            <button onClick={()=>setTutorialStep(2)} className="w-full py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-extrabold text-xs tracking-widest uppercase transition-all shadow-md">
              {lang==="fr"?"SUIVANT":"NEXT"}
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden min-h-0 w-full">
        <aside className="w-56 shrink-0 border-r border-zinc-200 dark:border-zinc-800 p-8 bg-zinc-50 dark:bg-zinc-950 flex flex-col justify-between">
          <div className="space-y-20">
            <h2 className="font-bold text-lg">
              <Link href="/" className="hover:text-cyan-500 dark:hover:text-cyan-400">{t.sidebar.home}</Link>
            </h2>
            <div className="space-y-20 text-zinc-800 dark:text-zinc-100 font-medium">
              <Link href="/chat"       className="block hover:text-cyan-500">{t.sidebar.chat}</Link>
              <Link href="/books"      className="block hover:text-cyan-500">{t.sidebar.books}</Link>
              <Link href="/calendar"   className="block hover:text-cyan-500">📅 {lang==="fr"?"Calendrier":"Calendar"}</Link>
              <Link href="/vitality"   className="block text-cyan-600 dark:text-cyan-400 font-bold">📈 {lang==="fr"?"Vitalite":"Vitality"}</Link>
              <Link href="/services"   className="block hover:text-cyan-500">💎 Services</Link>
              <Link href="/account"    className="block hover:text-cyan-500">👤 {lang==="fr"?"Compte":"Account"}</Link>
              <Link href="/horizonweb" className="block hover:text-cyan-500">📡 HorizonWeb</Link>
              <hr className="border-zinc-200 dark:border-zinc-800 my-4" />
              <Link href="/history"    className="block hover:text-amber-500">⭐ {lang==="fr"?"Historique":"History"}</Link>
            </div>
          </div>
          <div className="pt-4 border-t border-zinc-200 dark:border-zinc-800 text-xs text-zinc-500">
            Status : <span className="text-cyan-500 dark:text-cyan-400 uppercase font-bold block">{safeTier === "connected_free" ? (lang === "fr" ? "Accès libre" : "FreeConnect") : safeTier}</span>
          </div>
        </aside>

        <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1.1fr_1.1fr_2.8fr] overflow-hidden bg-white dark:bg-black h-full w-full">
          {/* FINANCES */}
          <section className="min-w-0 xl:border-r border-b xl:border-b-0 border-zinc-200 dark:border-zinc-900 bg-zinc-50/10 dark:bg-zinc-950/5 p-4 flex flex-col h-full overflow-hidden">
            <div className="bg-zinc-100 dark:bg-zinc-900/60 border border-zinc-200 dark:border-transparent rounded-2xl p-3 flex flex-col items-center shrink-0 h-40 justify-center mb-3 shadow-sm">
              <div className="relative w-28 h-28 flex items-center justify-center">
                <svg className="w-full h-full -rotate-90 relative z-10" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="40" stroke={theme==="dark"?"#18181b":"#e4e4e7"} strokeWidth="9" fill="transparent" />
                  <circle cx="50" cy="50" r="40" stroke="#06b6d4" strokeWidth="9" fill="transparent"
                    strokeDasharray={251.2} strokeDashoffset={251.2-(251.2*budgetPercentage)/100}
                    className="transition-all duration-500 stroke-cyan-500 filter drop-shadow-[0_0_4px_rgba(6,182,212,0.6)]" />
                </svg>
                <div className="absolute z-20 bg-white dark:bg-zinc-950/90 rounded-full w-[76%] h-[76%] flex flex-col justify-center items-center border border-zinc-200 dark:border-zinc-800 text-center px-1">
                  <span className="text-zinc-400 dark:text-zinc-500 text-[9px] uppercase font-bold tracking-wider">{dict.spent}</span>
                  <div className="flex flex-col items-center leading-none">
                    {(totalSpentUSD>0||totalSpentEUR===0) && <span className="text-lg font-black text-cyan-400">{totalSpentUSD.toFixed(2)}</span>}
                    {totalSpentEUR>0 && <span className="text-sm font-black text-emerald-400">{totalSpentEUR.toFixed(2)}€</span>}
                  </div>
                  {isEditingBudget ? (
                    <input type="number" value={inputBudgetGoal} onChange={e=>setInputBudgetGoal(e.target.value)}
                      onBlur={saveBudgetGoal} onKeyDown={e=>e.key==="Enter"&&saveBudgetGoal()}
                      className="w-16 bg-zinc-100 dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-700 text-center text-sm text-black dark:text-white rounded p-1 mt-1 focus:outline-none font-bold" autoFocus />
                  ) : (
                    <span className="text-zinc-400 dark:text-zinc-500 text-sm cursor-pointer hover:text-cyan-500 font-bold mt-1" onClick={()=>setIsEditingBudget(true)}>
                      / {budgetGoal} ✏️
                    </span>
                  )}
                </div>
              </div>
            </div>

            <div className="shrink-0 border-b border-zinc-200 dark:border-zinc-900 pb-3">
              <form onSubmit={handleManualExpenseSubmit} className="flex flex-col gap-1.5">
                <div className="grid grid-cols-[1fr_5rem_3rem] gap-1.5">
                  <input type="text" placeholder="Titre" value={manualExpenseTitle} onChange={e=>setManualExpenseTitle(e.target.value)}
                    className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-3 py-2 text-xs focus:outline-none shadow-inner" />
                  <input type="number" placeholder="Montant" value={manualExpenseAmount} onChange={e=>setManualExpenseAmount(e.target.value)}
                    className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-2 py-2 text-xs text-center focus:outline-none font-mono shadow-inner" />
                  <select value={manualExpenseCurrency} onChange={e=>setManualExpenseCurrency(e.target.value as any)}
                    className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl text-xs text-center font-bold cursor-pointer focus:outline-none">
                    <option value="$">CA$</option><option value="US$">US$</option><option value="€">€</option>
                  </select>
                </div>
                <div className="grid grid-cols-[1fr_2.5rem] gap-1.5">
                  <input type="date" value={manualExpenseDate} onChange={e=>setManualExpenseDate(e.target.value)}
                    className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-2.5 py-1.5 text-xs focus:outline-none shadow-inner" />
                  <button type="submit" className="bg-cyan-600 hover:bg-cyan-500 text-white text-sm rounded-xl font-bold transition flex items-center justify-center">+</button>
                </div>
              </form>
            </div>

            <div className="flex-1 overflow-y-auto mt-3 space-y-1.5 pr-1 min-h-0">
              <h3 className="text-xs font-bold text-cyan-400 mb-1.5 uppercase tracking-wide">{dict.fluxFin}</h3>
              {expenses.length===0 ? (
                <p className="text-zinc-400 dark:text-zinc-700 text-xs italic text-center pt-4">{dict.noTrans}</p>
              ) : expenses.map(exp => (
                <div key={exp.id} className="flex justify-between items-center bg-white dark:bg-zinc-900/40 border border-zinc-100 dark:border-zinc-900/80 px-3 py-2 rounded-xl hover:border-cyan-500/30 shadow-sm transition">
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-zinc-700 dark:text-zinc-200 truncate text-[13px]">{exp.title}</p>
                    <span className="text-[10px] text-zinc-400">📅 {exp.date}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-2">
                    <span className={`font-mono font-bold text-sm ${exp.currency==="€"?"text-emerald-400":exp.currency==="US$"?"text-blue-400":"text-cyan-400"}`}>
                      {exp.currency==="$"?`CA$${exp.amount.toFixed(2)}`:exp.currency==="US$"?`US$${exp.amount.toFixed(2)}`:`${exp.amount.toFixed(2)}€`}
                    </span>
                    <button onClick={()=>deleteExpense(exp.id)} className="text-zinc-400 hover:text-red-500 text-xs">✕</button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* NUTRITION */}
          <section className="min-w-0 xl:border-r border-b xl:border-b-0 border-zinc-200 dark:border-zinc-900 bg-zinc-50/10 dark:bg-zinc-950/5 p-4 flex flex-col h-full overflow-hidden">
            <div className="bg-zinc-100 dark:bg-zinc-900/60 border border-zinc-200 dark:border-transparent rounded-2xl p-3 flex flex-col justify-center shrink-0 h-40 w-full mb-3 shadow-sm">
              <div className="flex justify-between items-center">
                <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">Calories</span>
                {isEditingCalories ? (
                  <input type="number" value={inputCalorieGoal} onChange={e=>setInputCalorieGoal(e.target.value)}
                    onBlur={saveCalorieGoal} onKeyDown={e=>e.key==="Enter"&&saveCalorieGoal()}
                    className="w-20 bg-zinc-100 dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-700 text-center text-sm text-black dark:text-white rounded p-1 focus:outline-none font-bold" autoFocus />
                ) : (
                  <span className="text-sm font-bold text-zinc-400 dark:text-zinc-500 font-mono cursor-pointer hover:text-emerald-500" onClick={()=>setIsEditingCalories(true)}>
                    {dict.goal}: <span className="text-emerald-400 font-black">{calorieGoal}</span> ✏️
                  </span>
                )}
              </div>
              <h4 className="text-2xl font-black text-emerald-400 my-0.5">{totalCaloriesEaten} <span className="text-xs font-normal text-zinc-400">kcal</span></h4>
              <div className="w-full bg-zinc-200 dark:bg-zinc-950 h-2.5 rounded-full overflow-hidden border border-zinc-300 dark:border-zinc-800 my-1 shadow-inner">
                <div className="bg-emerald-500 h-full transition-all duration-500" style={{width:`${Math.min((totalCaloriesEaten/calorieGoal)*100,100)}%`}} />
              </div>
              <div className="text-[10px] text-zinc-500 dark:text-zinc-400 font-semibold">{dict.remaining} : <span className="font-mono text-emerald-400 font-black">{calorieRemaining} kcal</span></div>
              <button type="button" onClick={()=>setShowProfileModal(true)}
                className="mt-2 w-full bg-emerald-600/10 hover:bg-emerald-600/25 border border-emerald-500/40 text-emerald-500 rounded-xl py-1.5 text-[11px] font-mono tracking-wider font-bold uppercase transition shadow-sm">
                {dict.btnCalc}
              </button>
            </div>

            <div className="shrink-0 border-b border-zinc-200 dark:border-zinc-900 pb-3">
              <form onSubmit={handleManualCalorieSubmit} className="grid grid-cols-[1fr_5rem_2.5rem] gap-1.5 items-stretch">
                <input type="text" placeholder="Repas" value={manualFoodName} onChange={e=>setManualFoodName(e.target.value)}
                  className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-3 py-2 text-xs focus:outline-none shadow-inner" />
                <input type="number" placeholder="kcal" value={manualCalories} onChange={e=>setManualCalories(e.target.value)}
                  className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-2 py-2 text-xs text-center focus:outline-none font-mono shadow-inner" />
                <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-xl font-bold transition flex items-center justify-center">+</button>
              </form>
            </div>

            <div className="flex-1 overflow-y-auto mt-3 space-y-1.5 pr-1 min-h-0">
              <h3 className="text-xs font-bold text-emerald-400 mb-1.5 uppercase tracking-wide">{dict.regVit}</h3>
              {caloriesList.length===0 ? (
                <p className="text-zinc-400 dark:text-zinc-700 text-xs italic text-center pt-4">{dict.noMeal}</p>
              ) : caloriesList.map(cal => (
                <div key={cal.id} className="flex justify-between items-center bg-white dark:bg-zinc-900/40 border border-zinc-100 dark:border-zinc-900/80 px-3 py-2 rounded-xl hover:border-emerald-500/30 shadow-sm transition">
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-zinc-700 dark:text-zinc-300 truncate text-[13px]">{cal.foodName}</p>
                    <span className="text-[10px] text-zinc-400">📅 {cal.date}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-2">
                    <span className="font-mono text-emerald-400 font-bold text-sm">{cal.calories} kcal</span>
                    <button onClick={()=>deleteCalorie(cal.id)} className="text-zinc-400 hover:text-red-500 text-xs">✕</button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* ECHO CONTROLLER */}
          <aside className="min-w-0 xl:border-l border-zinc-200 dark:border-zinc-800 flex flex-col bg-zinc-50 dark:bg-zinc-950 overflow-hidden relative h-full w-full">
            <div className="p-3 border-b border-zinc-200 dark:border-zinc-900 bg-zinc-100 dark:bg-zinc-900/60 shrink-0 flex items-center justify-between gap-2 shadow-sm">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
                <h2 className="font-bold text-xs text-zinc-800 dark:text-zinc-100 uppercase font-mono tracking-wider">{dict.ctrlTitle}</h2>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto overflow-x-hidden min-h-0 bg-white dark:bg-black/20">
              {echoMessages.length===0 ? (
                <div className="h-full flex flex-col items-center justify-center gap-3 p-6">
                  {!tutorialStep && (
                    <div className={`w-12 h-12 bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-full flex items-center justify-center shadow-inner ${echoState==="idle"?"echo-idle":echoState==="thinking"?"echo-thinking":"echo-speaking"}`}>
                      <img src="/echo1.png" alt="Echo" className="w-full h-full object-cover rounded-full" />
                    </div>
                  )}
                  <p className="text-zinc-400 dark:text-zinc-600 text-xs italic text-center">
                    {lang==="fr"?"En attente d'instructions...":"Awaiting commands..."}
                  </p>
                </div>
              ) : (
                <div className="max-w-none px-5 py-6 flex flex-col gap-7">
                  {echoMessages.map((msg, idx) => {
                    const isEcho  = /^Echo\s*:/i.test(msg.raw);
                    const isUser  = /^(You|Toi)\s*:/i.test(msg.raw);
                    const isLastE = isEcho && idx===lastEchoIndex;
                    const text    = msg.raw.replace(/^(Echo|You|Toi)\s*:\s*/i,"");
                    if (text.startsWith("[SYNCHRONISATION PROFIL]")) return null;
                    
                    if (isEcho) {
                      // TRAITEMENT DE SÉCURITÉ ANTI COUPLAGE TEXTUEL DE \n COMPILÉ PAR LES LLM
                      const cleanText = text.replace(/\\n/g, "\n");
                      
                      return (
                        <div key={idx} className="flex flex-col gap-3 animate-in fade-in duration-300">
                          <div className="flex items-center gap-2">
                            <img src="/echo1.png" alt="Echo"
                              className={`w-10 h-10 rounded-full object-contain shrink-0 border border-zinc-200 dark:border-zinc-800 ${isLastE?echoState==="thinking"?"echo-thinking":echoState==="speaking"?"echo-speaking":"echo-idle":"echo-idle"}`} />
                            <span className="text-zinc-500 dark:text-zinc-400 text-[11px] font-mono uppercase tracking-widest font-bold">Echo</span>
                          </div>
                          <div className="text-zinc-800 dark:text-zinc-200 text-[14px] leading-7 font-normal tracking-wide selection:bg-cyan-500/30 flex flex-col gap-4 pl-8">
                            {cleanText
                              .split(/\n\n+/)
                              .map(block => block.trim())
                              .filter(block => block.length > 0)
                              .map((block, i) => <p key={i} className="whitespace-pre-wrap break-words">{block}</p>)}
                          </div>
                        </div>
                      );
                    }
                    if (isUser) return (
                      <div key={idx} className="flex flex-col items-end animate-in fade-in duration-200">
                        {msg.imageB64 && <img src={msg.imageB64} alt="upload" className="max-w-[150px] max-h-[120px] rounded-xl border border-zinc-700 object-cover shadow-md mb-1.5" />}
                        <div className="max-w-[80%] text-right">
                          <p className="text-zinc-700 dark:text-zinc-300 text-[13px] leading-6 tracking-wide bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl px-4 py-2.5 inline-block text-left whitespace-pre-wrap break-words selection:bg-cyan-500/30">{text}</p>
                        </div>
                      </div>
                    );
                    return null;
                  })}
                  <div ref={bottomRef} />
                </div>
              )}
            </div>

            <div className="p-4 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 shrink-0">
              {imageBase64 && (
                <div className="mb-2 flex items-center justify-between bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1.5 rounded-xl text-[11px] text-emerald-600 dark:text-emerald-400">
                  <div className="flex items-center gap-2 truncate">
                    <img src={imageBase64} alt="preview" className="w-8 h-8 rounded object-cover border border-emerald-500/30 shrink-0" />
                    <span className="truncate font-medium">{imageName||(lang==="fr"?"Image prete":"Image ready")}</span>
                  </div>
                  <button onClick={()=>{setImageBase64(null);setImageName(null);}} className="text-zinc-400 hover:text-red-500 font-bold ml-2 shrink-0">X</button>
                </div>
              )}
              <input type="file" accept="image/*" ref={fileInputRef} onChange={handleFileChange} className="hidden" />
              <div className="flex gap-2 items-end">
                <textarea value={inputEcho} maxLength={getMessageMaxLength(safeTier)}
                  onChange={e=>setInputEcho(e.target.value)}
                  onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();handleSendEcho();}}}
                  rows={3} placeholder={dict.placeholder}
                  className="flex-1 bg-white dark:bg-zinc-900 text-black dark:text-white border border-zinc-200 dark:border-zinc-800 rounded-xl p-3 text-xs resize-none focus:outline-none focus:border-zinc-400 dark:focus:border-zinc-700 transition-colors leading-relaxed shadow-inner placeholder-zinc-400" />
                <div className="flex flex-col gap-2 w-12 shrink-0 self-end">
                  <button type="button" onClick={()=>isImageButtonLocked?setShowPremiumModal(true):fileInputRef.current?.click()}
                    className={`h-9 w-full rounded-xl flex items-center justify-center border text-sm transition-all ${isImageButtonLocked?"cursor-not-allowed border-zinc-200 dark:border-zinc-800 text-zinc-400 bg-zinc-100 dark:bg-zinc-900":imageBase64?"border-emerald-500/40 text-emerald-400 bg-emerald-500/10":"border-zinc-200 dark:border-zinc-800 text-zinc-400 hover:border-zinc-400 dark:hover:border-zinc-600 bg-white dark:bg-zinc-900"}`}>
                    {isImageButtonLocked?"🔒":imageBase64?"V":"IMG"}
                  </button>
                  <button type="button" onClick={lancerDictation}
                    className={`h-9 w-full rounded-xl flex items-center justify-center border text-sm transition-all ${isListening?"bg-red-600 border-red-500 text-white animate-pulse":"border-cyan-500/30 text-cyan-500 bg-cyan-500/10 hover:border-cyan-400"}`}>
                    {isListening?"●":"MIC"}
                  </button>
                  <button onClick={()=>handleSendEcho()}
                    className="h-9 w-full bg-cyan-600 hover:bg-cyan-500 rounded-xl flex items-center justify-center text-white text-sm font-bold transition-all shadow-md">
                    OK
                  </button>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </div>

      {/* PROFILE MODAL */}
      {showProfileModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <form onSubmit={handleSubmitModalProfile}
            className="bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 p-6 rounded-2xl max-w-sm w-full shadow-2xl flex flex-col gap-4 animate-in zoom-in-95 duration-200 text-xs text-zinc-800 dark:text-zinc-100">
            <div className="flex justify-between items-center border-b border-zinc-100 dark:border-zinc-900/60 pb-2">
              <h3 className="text-base font-bold text-emerald-400 flex items-center gap-1.5">{dict.title}</h3>
              <button type="button" onClick={()=>setShowProfileModal(false)} className="text-zinc-400 hover:text-red-500 font-bold text-sm">X</button>
            </div>
            <p className="text-zinc-500 dark:text-zinc-400 leading-relaxed text-[11px]">{dict.desc}</p>
            <div className="flex flex-col gap-1">
              <div className="flex justify-between items-center mb-0.5">
                <label className="font-bold text-zinc-600 dark:text-zinc-400">{dict.weight}</label>
                <div className="flex bg-zinc-100 dark:bg-zinc-900 rounded-lg p-0.5 border border-zinc-200 dark:border-zinc-800">
                  {(["kg","lbs"] as const).map(u=>(
                    <button key={u} type="button" onClick={()=>setWeightUnit(u)}
                      className={`px-2 py-0.5 rounded text-[10px] font-black uppercase transition-all ${weightUnit===u?"bg-emerald-500 text-white":"text-zinc-400"}`}>{u}</button>
                  ))}
                </div>
              </div>
              <div className="relative">
                <input required type="number" step="0.1" value={modalWeight} onChange={e=>setModalWeight(e.target.value)}
                  className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-2.5 font-mono font-bold text-sm focus:outline-none" />
                <span className="absolute right-3 top-3 font-mono font-bold text-zinc-400 uppercase text-[11px]">{weightUnit}</span>
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <div className="flex justify-between items-center mb-0.5">
                <label className="font-bold text-zinc-600 dark:text-zinc-400">{dict.height}</label>
                <div className="flex bg-zinc-100 dark:bg-zinc-900 rounded-lg p-0.5 border border-zinc-200 dark:border-zinc-800">
                  {(["cm","ft"] as const).map(u=>(
                    <button key={u} type="button" onClick={()=>setHeightUnit(u)}
                      className={`px-2 py-0.5 rounded text-[10px] font-black uppercase transition-all ${heightUnit===u?"bg-emerald-500 text-white":"text-zinc-400"}`}>{u}</button>
                  ))}
                </div>
              </div>
              {heightUnit==="cm" ? (
                <div className="relative">
                  <input required type="number" value={modalHeight} onChange={e=>setModalHeight(e.target.value)}
                    className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-2.5 font-mono font-bold text-sm focus:outline-none" />
                  <span className="absolute right-3 top-3 font-mono font-bold text-zinc-400 uppercase text-[11px]">cm</span>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  <div className="relative">
                    <input required type="number" placeholder="Pieds" value={modalHeight} onChange={e=>setModalHeight(e.target.value)}
                      className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-2.5 font-mono font-bold text-sm focus:outline-none text-center" />
                    <span className="absolute right-3 top-3 font-mono font-bold text-zinc-400 text-[11px]">ft</span>
                  </div>
                  <div className="relative">
                    <input type="number" placeholder="Pouces" value={modalHeightInches} onChange={e=>setModalHeightInches(e.target.value)}
                      className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-2.5 font-mono font-bold text-sm focus:outline-none text-center" />
                    <span className="absolute right-3 top-3 font-mono font-bold text-zinc-400 text-[11px]">in</span>
                  </div>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3 pb-2">
              <div className="flex flex-col gap-1">
                <label className="font-bold text-zinc-600 dark:text-zinc-400">{dict.age}</label>
                <input required type="number" value={modalAge} onChange={e=>setModalAge(e.target.value)}
                  className="bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-2.5 font-mono font-bold text-sm focus:outline-none" />
              </div>
              <div className="flex flex-col gap-1">
                <label className="font-bold text-zinc-600 dark:text-zinc-400">{dict.gender}</label>
                <select value={modalGender} onChange={e=>setModalGender(e.target.value)}
                  className="bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-2.5 font-bold focus:outline-none h-[39px] cursor-pointer text-sm">
                  <option value="homme">{dict.male}</option>
                  <option value="femme">{dict.female}</option>
                </select>
              </div>
            </div>
            <button type="submit" className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3 rounded-xl transition shadow-md uppercase tracking-wide text-xs">
              {dict.btnApply}
            </button>
          </form>
        </div>
      )}

      <PremiumRequiredModal open={showPremiumModal} onClose={() => setShowPremiumModal(false)} />
    </main>
  );
}