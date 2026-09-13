"use strict";

const DEFAULT_QUERY =
  "Tìm cho tôi chuyến bay từ HAN đi SGN dưới 2 triệu, rồi cho biết thời tiết SGN nên mặc gì?";

const PRESETS = {
  multi: DEFAULT_QUERY,
  flight: "Có chuyến bay nào từ HAN đi DAD giá dưới 1.5 triệu không?",
  weather: "Thời tiết ở Đà Nẵng DAD hiện tại thế nào?",
  empty: "Tìm cho tôi chuyến bay từ SGN đi HAN dưới 500k.",
  faq: "Chính sách đổi trả vé máy bay Vinpearl như thế nào?",
};

const FLIGHTS = [
  {
    flight_number: "VN213",
    origin: "HAN",
    destination: "SGN",
    departure_time: "08:00",
    price_vnd: 1850000,
    airline: "Vietnam Airlines",
  },
  {
    flight_number: "VJ151",
    origin: "HAN",
    destination: "SGN",
    departure_time: "11:30",
    price_vnd: 1450000,
    airline: "Vietjet Air",
  },
  {
    flight_number: "QH202",
    origin: "HAN",
    destination: "DAD",
    departure_time: "09:15",
    price_vnd: 1200000,
    airline: "Bamboo Airways",
  },
  {
    flight_number: "VN110",
    origin: "DAD",
    destination: "HAN",
    departure_time: "16:45",
    price_vnd: 1350000,
    airline: "Vietnam Airlines",
  },
];

const WEATHER = {
  SGN: {
    city: "TP. Hồ Chí Minh",
    temperature_c: 32,
    condition: "Rainy",
    humidity_pct: 85,
    recommendation: "Mang ô/dù, áo mưa nhẹ, quần áo thoáng mát.",
  },
  HAN: {
    city: "Hà Nội",
    temperature_c: 22,
    condition: "Cloudy",
    humidity_pct: 70,
    recommendation: "Áo khoác mỏng, trang phục thu đông.",
  },
  DAD: {
    city: "Đà Nẵng",
    temperature_c: 28,
    condition: "Sunny",
    humidity_pct: 60,
    recommendation: "Kem chống nắng, kính râm, mũ rộng vành.",
  },
};

const CITY_ALIASES = {
  han: "HAN",
  "ha noi": "HAN",
  hanoi: "HAN",
  sgn: "SGN",
  "ho chi minh": "SGN",
  "thanh pho ho chi minh": "SGN",
  "tp ho chi minh": "SGN",
  "sai gon": "SGN",
  dad: "DAD",
  "da nang": "DAD",
};

const $ = (selector) => document.querySelector(selector);
const queryInput = $("#query");
const maxIterations = $("#max-iterations");
const iterationValue = $("#iteration-value");
const runButton = $("#run-demo");
const dataStatus = $("#data-status");
const baselineAnswer = $("#baseline-answer");
const agentAnswer = $("#agent-answer");
const agentStatus = $("#agent-status");
const toolCount = $("#tool-count");
const iterationCount = $("#iteration-count");
const traceList = $("#trace-list");
const traceSummary = $("#trace-summary");

function foldText(value) {
  return String(value)
    .toLocaleLowerCase("vi")
    .replace(/đ/g, "d")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function formatVnd(value) {
  return `${new Intl.NumberFormat("vi-VN").format(value)} VND`;
}

function locationOccurrences(text) {
  const occurrences = [];
  const aliases = Object.entries(CITY_ALIASES).sort(
    ([first], [second]) => second.length - first.length,
  );

  aliases.forEach(([alias, code]) => {
    const expression = new RegExp(`(^|[^\\w])${alias.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?!\\w)`, "g");
    let match;
    while ((match = expression.exec(text)) !== null) {
      occurrences.push({ position: match.index + match[1].length, code });
    }
  });

  return occurrences.sort((first, second) => first.position - second.position);
}

function extractBudget(text) {
  const expression = /(^|[^\d])(\d{1,3}(?:[,.]\d{3})+|\d+(?:[,.]\d+)?)\s*(trieu|tr|million|k|nghin|ngan|vnd|dong)?\b/g;
  const values = [];
  let match;

  while ((match = expression.exec(text)) !== null) {
    const [, prefix, numberText, unitValue] = match;
    const unit = unitValue || "";
    let value;

    if (["trieu", "tr", "million"].includes(unit)) {
      value = Number.parseFloat(numberText.replace(",", ".")) * 1000000;
    } else if (["k", "nghin", "ngan"].includes(unit)) {
      value = Number.parseFloat(numberText.replace(",", ".")) * 1000;
    } else {
      value = Number.parseInt(numberText.replace(/[,.]/g, ""), 10);
    }

    if (Number.isFinite(value) && value > 0) {
      values.push({ position: match.index + prefix.length, value: Math.trunc(value) });
    }
  }

  if (!values.length) return null;
  const budgetTerms = ["duoi", "toi da", "gia", "ngan sach", "under", "budget"];
  return (
    values.find(({ position }) => {
      const context = text.slice(Math.max(0, position - 30), position);
      return budgetTerms.some((term) => context.includes(term));
    }) || values[0]
  ).value;
}

function analyzeQuery(query) {
  const normalized = foldText(query);
  const occurrences = locationOccurrences(normalized);
  const codes = [...new Set(occurrences.map(({ code }) => code))];
  const isFaq = ["chinh sach", "doi tra", "hoan ve", "refund policy"].some((term) =>
    normalized.includes(term),
  );
  const asksWeather = [
    "thoi tiet",
    "weather",
    "nhiet do",
    "temperature",
    "mac gi",
    "trang phuc",
    "outfit",
  ].some((term) => normalized.includes(term));
  const asksFlight =
    !isFaq &&
    (["chuyen bay", "flight", "dat ve", "tim ve"].some((term) => normalized.includes(term)) ||
      /\bve\b/.test(normalized) ||
      (codes.length >= 2 && /\b(tu|from|di|den|toi|to)\b/.test(normalized)));
  const origin = codes[0] || null;
  const destination = codes[1] || null;
  const weatherMarker = /thoi tiet|weather|nhiet do|temperature|mac gi|trang phuc|outfit/.exec(normalized);
  const weatherCity = weatherMarker
    ? (occurrences.find(({ position }) => position >= weatherMarker.index) || {}).code || destination || codes[0] || null
    : destination || codes[0] || null;
  const maxPrice = extractBudget(normalized) || 5000000;
  const missing = [];
  const steps = [];

  if (asksFlight && (!origin || !destination)) missing.push("điểm đi và điểm đến");
  if (asksWeather && !weatherCity) missing.push("thành phố cần xem thời tiết");
  if (asksFlight && origin && destination) steps.push("flight");
  if (asksWeather && weatherCity) steps.push("weather");

  return {
    isFaq,
    asksFlight,
    asksWeather,
    origin,
    destination,
    weatherCity,
    maxPrice,
    steps,
    missingMessage: missing.length ? `Bạn vui lòng cung cấp ${missing.join(" và ")}.` : "",
  };
}

function getFlightInfo(origin, destination, maxPrice) {
  return FLIGHTS.filter(
    (flight) =>
      flight.origin === origin &&
      flight.destination === destination &&
      flight.price_vnd <= maxPrice,
  );
}

function getWeatherForecast(cityCode) {
  return WEATHER[cityCode] || { error: `Không có dữ liệu thời tiết cho ${cityCode}.` };
}

function latestObservation(observations, tool) {
  return [...observations].reverse().find((item) => item.tool === tool)?.observation;
}

function formatFlights(observation, intent) {
  if (observation?.error) return `Tôi chưa thể tra cứu chuyến bay: ${observation.error}`;
  if (!Array.isArray(observation)) return "Tôi nhận được dữ liệu chuyến bay không hợp lệ.";
  if (!observation.length) {
    return `Không tìm thấy chuyến bay phù hợp từ ${intent.origin} đến ${intent.destination} với giá tối đa ${formatVnd(intent.maxPrice)}.`;
  }

  const detail = observation
    .map(
      (flight) =>
        `${flight.flight_number} (${flight.airline}) lúc ${flight.departure_time}, ${formatVnd(flight.price_vnd)}`,
    )
    .join("; ");
  return `Các chuyến bay phù hợp: ${detail}.`;
}

function formatWeather(observation) {
  if (observation?.error) return `Tôi chưa thể tra cứu thời tiết: ${observation.error}`;
  if (!observation || typeof observation !== "object") return "Tôi nhận được dữ liệu thời tiết không hợp lệ.";

  const details = [
    observation.temperature_c !== undefined ? `${observation.temperature_c}°C` : null,
    observation.condition,
    observation.humidity_pct !== undefined ? `độ ẩm ${observation.humidity_pct}%` : null,
  ].filter(Boolean);
  const recommendation = observation.recommendation
    ? ` Gợi ý trang phục: ${observation.recommendation}`
    : "";
  return `Thời tiết tại ${observation.city}: ${details.join(", ")}.${recommendation}`;
}

function buildAnswer(intent, observations) {
  if (intent.isFaq) {
    return "Với vé máy bay Vinpearl, tôi không có dữ liệu chính sách đổi trả chi tiết trong dữ liệu mô phỏng. Bạn nên kiểm tra điều kiện của hạng vé hoặc liên hệ nơi bán để được xác nhận.";
  }

  const parts = [];
  if (intent.asksFlight) {
    const flight = latestObservation(observations, "get_flight_info");
    if (flight !== undefined) parts.push(formatFlights(flight, intent));
    else if (!intent.origin || !intent.destination) parts.push(intent.missingMessage);
    else parts.push("Tôi chưa thể hoàn tất tra cứu chuyến bay.");
  }
  if (intent.asksWeather) {
    const weather = latestObservation(observations, "get_weather_forecast");
    if (weather !== undefined) parts.push(formatWeather(weather));
    else if (!intent.weatherCity) parts.push(intent.missingMessage);
    else parts.push("Tôi chưa thể hoàn tất tra cứu thời tiết.");
  }
  if (!parts.length) {
    return intent.missingMessage || "Tôi có thể hỗ trợ tìm chuyến bay hoặc tra cứu thời tiết khi bạn cung cấp thông tin cần thiết.";
  }
  return parts.filter(Boolean).join(" ");
}

function nextThought(intent, attempted) {
  const next = intent.steps.find((step) => !attempted.has(step));
  if (next === "flight") return "Tra cứu chuyến bay theo hành trình và ngân sách đã nêu.";
  if (next === "weather") return "Tra cứu thời tiết tại địa điểm được hỏi.";
  if (intent.isFaq) return "Trả lời thận trọng vì không có dữ liệu chính sách chi tiết.";
  if (intent.missingMessage) return "Xác định thông tin còn thiếu trước khi tra cứu.";
  return "Tổng hợp dữ liệu đã quan sát để trả lời khách hàng.";
}

function runAgent(query, max) {
  const intent = analyzeQuery(query);
  const trace = [];
  const observations = [];
  const attempted = new Set();

  for (let iteration = 1; iteration <= max; iteration += 1) {
    const next = intent.steps.find((step) => !attempted.has(step));
    const thought = nextThought(intent, attempted);

    if (!next) {
      const answer = buildAnswer(intent, observations);
      trace.push({
        iteration,
        thought,
        action: null,
        observation: "Đã có đủ thông tin để trả lời.",
        answer,
      });
      return { status: "completed", answer, iterations: iteration, trace };
    }

    let action;
    let observation;
    if (next === "flight") {
      action = {
        name: "get_flight_info",
        args: { origin: intent.origin, destination: intent.destination, max_price: intent.maxPrice },
      };
      observation = getFlightInfo(intent.origin, intent.destination, intent.maxPrice);
    } else {
      action = { name: "get_weather_forecast", args: { city_code: intent.weatherCity } };
      observation = getWeatherForecast(intent.weatherCity);
    }

    trace.push({ iteration, thought, action, observation });
    observations.push({ tool: action.name, observation });
    attempted.add(next);

    if (intent.steps.length === 1) {
      const answer = buildAnswer(intent, observations);
      trace[trace.length - 1].answer = answer;
      return { status: "completed", answer, iterations: iteration, trace };
    }
  }

  const partial = buildAnswer(intent, observations);
  return {
    status: "max_iterations_reached",
    answer: `Không thể hoàn thành trong số bước tối đa.${partial ? ` Thông tin đã thu thập: ${partial}` : ""}`,
    iterations: max,
    trace,
  };
}

function setPreset(name) {
  document.querySelectorAll(".preset").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.preset === name);
  });
}

function codeBlock(value, extraClass = "") {
  const pre = document.createElement("pre");
  pre.className = `trace-code ${extraClass}`.trim();
  pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return pre;
}

function renderTrace(trace) {
  traceList.replaceChildren();
  trace.forEach((entry, index) => {
    const item = document.createElement("li");
    item.className = "trace-item";

    const number = document.createElement("span");
    number.className = "trace-step";
    number.textContent = entry.iteration;

    const details = document.createElement("details");
    details.className = "trace-details";
    details.open = index === 0 || index === trace.length - 1;

    const summary = document.createElement("summary");
    const summaryText = document.createElement("span");
    const title = document.createElement("span");
    title.className = "trace-title";
    title.textContent = entry.action ? `Action · ${entry.action.name}` : "Final Answer";
    const subtitle = document.createElement("span");
    subtitle.className = "trace-subtitle";
    subtitle.textContent = entry.thought;
    summaryText.append(title, subtitle);
    summary.append(summaryText);

    const content = document.createElement("div");
    content.className = "trace-content";
    const thought = document.createElement("p");
    thought.innerHTML = `<strong>Thought:</strong> `;
    thought.append(document.createTextNode(entry.thought));
    content.append(thought);
    if (entry.action) content.append(codeBlock({ Action: entry.action }));
    content.append(codeBlock({ Observation: entry.observation }));
    if (entry.answer) {
      const final = document.createElement("p");
      final.innerHTML = "<strong>Final Answer:</strong> ";
      final.append(document.createTextNode(entry.answer));
      content.append(final);
    }

    details.append(summary, content);
    item.append(number, details);
    traceList.append(item);
  });
}

function render(result) {
  baselineAnswer.textContent =
    "Tôi chưa có quyền truy cập dữ liệu chuyến bay hoặc thời tiết trong chế độ chatbot cơ bản.";
  agentAnswer.textContent = result.answer;
  agentStatus.textContent = result.status;
  agentStatus.classList.toggle("mini-badge--limit", result.status !== "completed");
  toolCount.textContent = result.trace.filter((entry) => entry.action).length;
  iterationCount.textContent = result.iterations;
  traceSummary.textContent =
    result.status === "completed"
      ? `Hoàn thành sau ${result.iterations} vòng lặp.`
      : `Đã dừng an toàn tại giới hạn ${result.iterations} vòng.`;
  renderTrace(result.trace);
}

function runDemo() {
  const query = queryInput.value.trim() || DEFAULT_QUERY;
  const maximum = Number(maxIterations.value);
  dataStatus.textContent = "Đang chạy";
  dataStatus.classList.add("is-running");
  runButton.disabled = true;

  try {
    const result = runAgent(query, maximum);
    render(result);
    dataStatus.textContent = "Đã cập nhật";
  } catch (error) {
    console.error("ReAct demo failed", error);
    agentAnswer.textContent = "Không thể chạy demo. Vui lòng tải lại trang và thử lại.";
    agentStatus.textContent = "error";
    agentStatus.classList.add("mini-badge--limit");
    traceSummary.textContent = "Trình duyệt gặp lỗi khi chạy mô phỏng.";
    traceList.replaceChildren();
    dataStatus.textContent = "Có lỗi";
  } finally {
    dataStatus.classList.remove("is-running");
    runButton.disabled = false;
  }
}

document.querySelectorAll(".preset").forEach((button) => {
  button.addEventListener("click", () => {
    const preset = button.dataset.preset;
    queryInput.value = PRESETS[preset];
    setPreset(preset);
    runDemo();
  });
});

queryInput.addEventListener("input", () => setPreset(""));
maxIterations.addEventListener("input", () => {
  iterationValue.value = `${maxIterations.value} vòng`;
  iterationValue.textContent = `${maxIterations.value} vòng`;
});
$("#run-demo").addEventListener("click", runDemo);
$("#reset").addEventListener("click", () => {
  queryInput.value = DEFAULT_QUERY;
  maxIterations.value = "5";
  iterationValue.value = "5 vòng";
  iterationValue.textContent = "5 vòng";
  setPreset("multi");
  runDemo();
});

queryInput.value = DEFAULT_QUERY;
runDemo();
