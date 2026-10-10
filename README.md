# 📊 LedgerLens AI

> **See your cash flow. Test your decisions. Plan with confidence.**
> An AI financial copilot that helps small businesses understand their cash position and safely test purchases or hires *before* spending a single rupee.

**Hacktoberfest Islamabad 2026 · Open AI Build Challenge**
Domain: **05 – Business & Productivity** · Venue: Cowork24, I-10 Islamabad · 10 October 2026

> ⚠️ **DEMO MODE:** All financial data in this project is simulated (fictional business *Northstar Office Supplies*). No real bank account is connected.

---

## 🧩 Problem

Small business owners in Pakistan usually track money in notebooks, WhatsApp messages or scattered spreadsheets. Because of that, they struggle to answer simple but critical questions:

- *"How much cash will I really have after next week's payroll and rent?"*
- *"Can I afford to hire someone at PKR 30,000/month?"*
- *"What happens to my balance if a customer pays late?"*

Bad answers lead to cash shortfalls, late supplier payments and risky decisions made on gut feeling.

## 💡 Solution

**LedgerLens AI** turns a business's transactions, bills and receivables into a clear, day-by-day cash-flow projection, and lets the owner ask an AI copilot in plain language about their position or a planned decision.

The key design rule: **the app calculates, the AI explains.**
All numbers (balances, projections, what-if results) come from a deterministic Python engine. The language model only explains those verified figures in simple words, so it cannot invent financial numbers.

### Features

| Module | What it does |
|---|---|
| **Overview** | Current cash, net cash flow for the reporting period (last 30 days), lowest projected balance and balance at the end of the horizon. |
| **Transactions** | Completed income and expenses that make up the current cash balance. |
| **Bills & Receivables** | Unpaid bills (obligations) and expected customer payments, with due dates and overdue flags. Configurable upcoming window: 7 / 30 / 60 days. |
| **What-If Simulator** | Test a one-time purchase, a recurring cost (e.g. a new salary), or a delayed payment and instantly see the new low point and end balance. |
| **AI Financial Copilot** | Chat interface that explains the current position or a specific what-if scenario: *Result → Reason → Risks → Assumptions → Bottom line*. |

### Example

> **User:** *Can I hire a new employee with 30k salary per month?*
> **Copilot:** Lowest projected balance drops from **PKR 71,000 → ≈ PKR 41,000** (26 Oct), and the horizon-end balance drops from **PKR 86,000 → ≈ PKR 56,000**. The cost recurs monthly, so the cash cushion becomes thinner unless receivables arrive on time.

## 🤖 AI Component (Open-Weight AI)

| Item | Details |
|---|---|
| **Model** | `openai/gpt-oss-120b`, an **open-weight** large language model released under the Apache-2.0 license |
| **Inference** | Served through the Groq API (fast hosted inference of the open-weight model) |
| **Role of the AI agent** | Reads the structured output of the cash-flow engine (current cash, obligations, receivables, daily cash movements, what-if results) and produces a structured explanation with risks and assumptions. It also answers follow-up questions in chat. |
| **Guardrails** | The agent is instructed to use only figures supplied by the app. Overdue receivables are excluded from projections, and assumptions are always stated. |

### Why AI is important here

Without the open-weight model the project would be only a spreadsheet-style dashboard. The AI agent is what lets a non-finance business owner **ask a decision question in plain English and get a reasoned, risk-aware answer** grounded in their own numbers. Removing it removes the copilot, the scenario discussion and the explanations, which are the core purpose of the product.

## 🏗️ Architecture

```
┌──────────────────────┐
│  Demo business data  │  transactions · bills · receivables (simulated, PKR)
└──────────┬───────────┘
           ▼
┌──────────────────────────────────────────┐
│  Cash-Flow Engine (Python 3.14)          │
│  • current cash & net flow               │
│  • day-by-day projection                 │
│  • what-if simulator (purchase / hire)   │
└──────────┬───────────────────────────────┘
           │ verified figures (JSON)
           ▼
┌──────────────────────────────────────────┐
│  AI Financial Copilot Agent              │
│  openai/gpt-oss-120b via Groq            │
│  explains numbers · risks · assumptions  │
└──────────┬───────────────────────────────┘
           ▼
┌──────────────────────────────────────────┐
│  Web UI  (Overview · Transactions ·      │
│  Bills & Receivables · What-If · Chat)   │
└──────────┬───────────────────────────────┘
           ▼
   ngrok tunnel → public HTTPS URL for live demo / sharing
```

**Flow in short:** data → calculations by the engine → structured facts passed to the agent → plain-language explanation shown in the UI. The LLM never does the arithmetic.

## 🛠️ Tech Stack

- **Language:** Python **3.14**
- **AI model:** `openai/gpt-oss-120b` (open-weight) via **Groq API**
- **AI agent:** prompt-driven financial copilot agent that consumes engine output and answers questions
- **Tunneling:** **ngrok** to expose the locally running app on a public HTTPS URL (used for the live demo and for letting judges open it from any device)
- **UI:** interactive web dashboard with tabs, sliders and chat input
- **Data:** simulated PKR dataset for a fictional business

## 🚀 Setup

### Prerequisites

- Python **3.14**
- A free [Groq API key](https://console.groq.com)
- (Optional) [ngrok](https://ngrok.com) account and auth token for public sharing

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/ledgerlens-ai.git
cd ledgerlens-ai
```

### 2. Create a virtual environment (Python 3.14)

```bash
python3.14 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Add your API key

Create a `.env` file (never commit it, it is listed in `.gitignore`):

```env
GROQ_API_KEY=your_groq_api_key_here
```

### 4. Run the app

```bash
# replace app.py with your entry file if it is different
python app.py
```

### 5. (Optional) Share publicly with ngrok

```bash
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
ngrok http 8501      # use the port your app runs on
```

ngrok prints a public `https://…ngrok-free.app` URL that anyone can open.

> 🔐 **No secrets are stored in this repository.** API keys and ngrok tokens are loaded from environment variables only.

## 🎬 Demo

1. Open the **Overview** tab and read your current position (PKR 200,000 cash, lowest projected PKR 71,000 on 26 Oct).
2. Go to **AI Financial Copilot** and click *"Explain my current cash-flow position."*
3. Ask: *"Can I hire a new employee with 30k salary per month?"*
4. Open the **What-If Simulator** to test other purchases and compare results.

*(Add screenshots / GIF / video link here: `docs/demo.gif`)*

## 👥 Team

| Member | Role & Contributions |
|---|---|
| **Merab Butt** | **Project lead & AI/agent engineer:** designed the AI Financial Copilot agent, prompt and guardrails (AI explains, app calculates), integrated `gpt-oss-120b` via Groq, and set up the ngrok sharing flow. |
| **Ayesha Hassan** | **Cash-flow engine & backend:** built the Python 3.14 calculation logic: current cash, net flow, day-by-day projection and the what-if simulator, plus simulated data. |
| **Fatima Zahra** | **UI/UX & testing:** designed the dashboard tabs (Overview, Transactions, Bills & Receivables), result tables and demo flow, and tested scenarios and edge cases such as overdue items. |

All three members contributed to ideation, testing, documentation and the final demo.

## ✅ Hacktoberfest Compliance Checklist

- [x] Open-weight AI (`gpt-oss-120b`) is central to the product (the copilot and explanations)
- [x] Original work: custom cash-flow engine, what-if simulator, agent prompting and UI
- [x] Public GitHub repository
- [x] Open-source license included (MIT, see below)
- [x] README with project, AI usage and setup
- [x] No API keys, passwords or tokens committed
- [x] Working demo available

## 📄 License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file.

## 🙏 Acknowledgements

- [OpenAI `gpt-oss-120b`](https://huggingface.co/openai/gpt-oss-120b): open-weight model (Apache-2.0)
- [Groq](https://groq.com): fast inference API
- [ngrok](https://ngrok.com): secure tunneling
- Python 3.14 and the open-source Python libraries listed in `requirements.txt`
- **Hacktoberfest Islamabad 2026**, powered by MLH and organized by CNCF Islamabad

---

*Built with ❤️ in Islamabad for Hacktoberfest 2026.*
