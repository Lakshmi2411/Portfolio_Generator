// api/chat.js
//
// Serverless backend for the portfolio's "Ask About This Portfolio" chat
// widget. Deploy this alongside portfolio.html (e.g. on Vercel — drop this
// file in an `api/` folder at your project root, Vercel auto-detects it,
// zero config needed).
//
// Why this exists as a separate serverless function rather than calling an
// LLM API directly from the browser: an API key embedded in static HTML is
// visible to anyone who views page source, and could be scraped and abused
// by strangers, burning your quota or violating your provider's terms. This
// function keeps the key server-side (as an environment variable Vercel
// injects at runtime) — the browser only ever talks to your own domain.
//
// Setup on Vercel:
//   1. Push this repo (portfolio.html + api/chat.js) to GitHub.
//   2. Import the repo in Vercel (vercel.com/new) — no build config needed.
//   3. In Project Settings -> Environment Variables, add GROQ_API_KEY
//      (free key from https://console.groq.com).
//   4. Deploy. The chat widget on your live portfolio will now work.
//
// ANTI-HALLUCINATION GUARDRAIL (same rule as every content-generation step
// in this project): the model is instructed to answer ONLY from the
// `context` payload the browser sends — which is the same real portfolio
// data already visible on the page (bio, project summaries, real detected
// tech, work experience, certifications). It must say "I don't have that
// information" rather than guess or invent anything not in that context.

const GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions";
const MODEL = "llama-3.3-70b-versatile";
const MAX_MESSAGE_LENGTH = 500;

function buildSystemPrompt(context) {
  return `You are answering questions on behalf of ${context.name || "this person"}, ` +
    `a candidate whose portfolio a recruiter or hiring manager is viewing. You represent ` +
    `them professionally and helpfully.

CRITICAL RULE: only answer using the information in the JSON context below. Never invent
projects, employers, skills, dates, or achievements that aren't in it. If someone asks
something the context doesn't cover, say you don't have that information rather than
guessing or making something up.

Context (their real portfolio data):
${JSON.stringify(context, null, 2)}

Answer concisely and naturally, like a knowledgeable assistant — not a wall of bullet points.
A sentence or two is usually enough unless the question genuinely needs more.`;
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const { message, context } = req.body || {};

  if (!message || typeof message !== "string" || !message.trim()) {
    res.status(400).json({ error: "Missing message" });
    return;
  }
  if (message.length > MAX_MESSAGE_LENGTH) {
    res.status(400).json({ error: "Message too long" });
    return;
  }

  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) {
    // Deliberately vague to the client — don't leak config details — but
    // specific in server logs for the deployer to diagnose.
    console.error("GROQ_API_KEY is not set in environment variables.");
    res.status(500).json({ reply: "Chat isn't configured yet — the site owner needs to set GROQ_API_KEY." });
    return;
  }

  try {
    const groqRes = await fetch(GROQ_API_URL, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: MODEL,
        messages: [
          { role: "system", content: buildSystemPrompt(context || {}) },
          { role: "user", content: message },
        ],
        temperature: 0.4,
        max_tokens: 400,
      }),
    });

    if (!groqRes.ok) {
      const errText = await groqRes.text();
      console.error("Groq API error:", groqRes.status, errText);
      res.status(502).json({ reply: "Sorry, I couldn't get an answer right now — please try again shortly." });
      return;
    }

    const data = await groqRes.json();
    const reply = data.choices?.[0]?.message?.content?.trim() || "Sorry, I didn't get a response.";
    res.status(200).json({ reply });
  } catch (err) {
    console.error("Chat handler error:", err);
    res.status(500).json({ reply: "Something went wrong answering that — please try again." });
  }
};