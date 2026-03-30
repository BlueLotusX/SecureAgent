---
name: weather_forecast_multi_day
description: Get today's and the next few days' weather for a city, using web search (no API key required). Optimized for Hong Kong as a primary example.
metadata: {"target_agents":"decision","emoji":"🌤️"}
allowed-tools: "get_current_datetime web_search web_search_with_content"
---

# Weather Forecast (multi‑day, via web search)

This Skill describes how to answer **“today’s weather and short‑term forecast”** questions
using web search tools, without relying on any specific weather API or curl commands.
It is optimized for questions like:

- "今天香港天气怎么样？"
- "What is the current weather in Hong Kong?"

You MUST follow this workflow whenever a user's request clearly asks for current weather
or near‑term forecast (e.g. today + the next 2–3 days) and this Skill is available.

---

## 1. Understand the user’s intent and location

1. Read the user's question and extract the **city name** (and optionally country/region).
2. If the user asks in Chinese, you should still keep the API request in English/Latin characters,
   but answer back in Chinese.
3. Focus on two main goals:
   - **Today’s weather** (temperature, conditions, precipitation, wind).
   - **Short‑term forecast** (at least the next 1–3 days).

If the user does not specify a city clearly, you may:
- Ask a clarifying question, OR
- Use web search with a broader query (e.g. "Hong Kong weather today") and then explain any ambiguity.

---

## 2. Get today’s date (for search context)

1. Call `get_current_datetime()` to obtain the current date/time.
2. Extract the **current date in ISO format** (e.g. `2026-03-10`).
3. Use this date in your search query to bias results towards **today’s** and **upcoming** forecasts.

---

## 3. Use web_search_with_content to retrieve a forecast page

Whenever possible, prefer `web_search_with_content` so that you get both search
results and the page content for summarization.

### Example: Hong Kong

```text
web_search_with_content(
  query="Hong Kong weather forecast today and next 3 days 2026-03-10",
  num_results=3,
  timeout=8
)
```

Guidelines:
- Replace `"Hong Kong"` with the actual city (in English) extracted from the user query.
- Replace `2026-03-10` with the actual date obtained from `get_current_datetime()`.
- You do NOT need to fix the domain (no hard‑coded website); let the search engine
  choose reliable weather sites, then read and summarize.

---

## 4. Extract structured information from search results

From the combined search + page content, you should extract:

- For **today**:
  - Temperature range (min / max, or “around X°C” if only approximate).
  - Main condition (sunny, cloudy, rainy, thunderstorms, etc.).
  - Any important precipitation / wind information.
- For **next 1–3 days**:
  - Daily high/low temperature trends.
  - Main conditions per day (e.g. “tomorrow: 多云，有小雨；后天：晴间多云”).

When multiple sources disagree, prefer:
- Official or well‑known weather sites (national meteorological services, major portals),
- Or explain briefly that forecasts differ and provide a reasonable range.

---

## 5. Answer the user in a concise, user‑friendly way

1. Use the same language as the user (Chinese if the question is Chinese).
2. First give **today’s summary**, then provide **short‑term forecast**.

Example (Chinese):

> 香港当前气温约 17℃，风速大约 5km/h，天气多云。
> 预计今晚至明天有零星小雨，气温在 15–19℃ 之间；后天起天气转晴，白天气温回升至 20℃ 左右。

3. Do **not** fabricate precise numbers if the sources only provide approximate
   descriptions; in这种情况下可以用区间或模糊表达（如“在 15–20℃ 左右”）。

---

## 6. Error handling and fallbacks

- If `web_search_with_content` fails or times out:
  - Retry once with a simpler query (e.g. `"Hong Kong weather today"`).
  - If it still fails, fall back to `web_search` and summarize based on titles/snippets.
- If there is no network connectivity or all weather pages are unreachable:
  - Clearly explain that **real‑time weather cannot be retrieved** due to network/API limits.
  - Do NOT invent exact temperatures; at most you may give climatological expectations
    (e.g. “香港三月通常气温在 15–22℃ 之间，但当前具体实时数据无法获取”).

---

This search‑based workflow is preferred over direct API or curl usage in this environment,
because it is more robust to API changes and does not require any special binaries.
