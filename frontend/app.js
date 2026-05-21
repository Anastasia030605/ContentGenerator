const state = {
  providers: [],
};

const els = {
  channelInfo: document.getElementById('channelInfo'),
  collectResult: document.getElementById('collectResult'),
  analysisResult: document.getElementById('analysisResult'),
  planResult: document.getElementById('planResult'),
  generateResult: document.getElementById('generateResult'),
  historyResult: document.getElementById('historyResult'),
  providerSelect: document.getElementById('providerSelect'),
  modelSelect: document.getElementById('modelSelect'),
  apiKey: document.getElementById('apiKey'),
  channelUsername: document.getElementById('channelUsername'),
};

function apiFetch(path, options = {}) {
  return fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  }).then(async (res) => {
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      // Если это ошибка 400 с сообщением о необходимости собрать посты
      if (res.status === 400 && body?.detail && body.detail.includes('Сначала соберите посты')) {
        throw new Error('Сначала соберите посты. Нажмите "Заполнить демонстрационными постами" или "Собрать посты" из Telegram канала.');
      }
      throw new Error(body?.detail || res.statusText || 'Ошибка запроса');
    }
    return body;
  });
}

function updateSelectOptions() {
  const providerId = els.providerSelect.value;
  const provider = state.providers.find((item) => item.id === providerId);
  els.modelSelect.innerHTML = '';
  if (!provider) {
    return;
  }
  provider.models.forEach((model) => {
    const option = document.createElement('option');
    option.value = model.id;
    option.textContent = `${model.label} ${model.description ? `(${model.description})` : ''}`;
    els.modelSelect.appendChild(option);
  });
}

function setResult(element, content) {
  if (typeof content === 'object') {
    // Если это ответ от API с полем plan (контент-план)
    if (content.plan && Array.isArray(content.plan)) {
      element.textContent = formatContentPlan(content.plan);
    } 
    // Если это ответ от API с полем post (сгенерированный пост)
    else if (content.post) {
      element.textContent = content.post;
    }
    // Если это обычный объект
    else {
      element.textContent = JSON.stringify(content, null, 2);
    }
  } else {
    element.textContent = content;
  }
}

function getSelectedModelData() {
  return {
    provider: els.providerSelect.value || undefined,
    model: els.modelSelect.value || undefined,
    api_key: els.apiKey.value || undefined,
  };
}

function getChannelUsername() {
  const username = els.channelUsername.value.trim();
  return username ? username.replace(/^@+/, '') : undefined;
}

function formatChannelInfo(data) {
  if (!data || !data.title) {
    return 'Не удалось загрузить информацию о канале.';
  }
  return `📺 ${data.title}
@${data.username}

👥 Подписчиков: ${(data.subscribers || 0).toLocaleString('ru-RU')}

📝 Описание:
${data.description || '(нет описания)'}`;
}

async function loadChannelInfo() {
  try {
    setResult(els.channelInfo, 'Загрузка...');
    const username = getChannelUsername();
    const path = username ? `/api/channel-info?channel_username=${encodeURIComponent(username)}` : '/api/channel-info';
    const info = await apiFetch(path);
    setResult(els.channelInfo, formatChannelInfo(info));
  } catch (error) {
    setResult(els.channelInfo, `Ошибка: ${error.message}`);
  }
}

async function collectPosts() {
  const limit = parseInt(document.getElementById('collectLimit').value, 10) || 50;
  const daysBack = parseInt(document.getElementById('collectDays').value, 10) || undefined;
  const channelUsername = getChannelUsername();
  if (!channelUsername) {
    setResult(els.collectResult, 'Введите @username Telegram-канала.');
    return;
  }

  try {
    setResult(els.collectResult, 'Запрос...');
    const payload = { limit, days_back: daysBack, channel_username: channelUsername };
    const data = await apiFetch('/api/collect', { method: 'POST', body: JSON.stringify(payload) });
    setResult(els.collectResult, `Собрано ${data.collected} постов\nКанал: ${data.channel}`);
  } catch (error) {
    setResult(els.collectResult, `Ошибка: ${error.message}`);
  }
}

function formatAnalysis(data) {
  if (!data || !data.summary) {
    return 'Нет данных для анализа. Сначала соберите посты.';
  }
  const s = data.summary;
  const bt = data.best_timing || {};
  const kw = data.keywords || [];
  const recs = data.recommendations || [];
  
  let result = `📊 АНАЛИЗ КАНАЛА\n`;
  result += `${'='.repeat(50)}\n\n`;
  
  result += `📈 СТАТИСТИКА\n`;
  result += `Всего постов: ${s.total_posts}\n`;
  result += `Период: ${s.date_range?.from?.slice(0, 10) || '?'} — ${s.date_range?.to?.slice(0, 10) || '?'}\n\n`;
  
  result += `👁️ ПРОСМОТРЫ\n`;
  result += `Среднее: ${Math.round(s.avg_views)}\n`;
  result += `Медиана: ${s.median_views}\n`;
  result += `Максимум: ${s.max_views}\n\n`;
  
  result += `⏱️ ВРЕМЯ ПУБЛИКАЦИИ\n`;
  result += `Лучший час: ${bt.best_hour || '?'}:00\n`;
  result += `Лучший день: ${bt.best_day || '?'}\n\n`;
  
  result += `🏆 ТОП СЛОВА\n`;
  kw.slice(0, 10).forEach((item, idx) => {
    const word = Array.isArray(item) ? item[0] : item;
    const count = Array.isArray(item) ? item[1] : 0;
    result += `${idx + 1}. ${word} (${count})\n`;
  });
  
  if (recs.length > 0) {
    result += `\n💡 РЕКОМЕНДАЦИИ\n`;
    recs.forEach(rec => {
      result += `• ${rec}\n`;
    });
  }
  
  return result;
}

function formatContentPlan(plan) {
  if (!Array.isArray(plan) || plan.length === 0) {
    return 'Контент-план пуст.';
  }
  
  let result = `📅 КОНТЕНТ-ПЛАН (${plan.length} постов)\n`;
  result += `${'='.repeat(50)}\n\n`;
  
  // Группируем по неделям
  const weeks = {};
  plan.forEach(item => {
    const week = item.week || 1;
    if (!weeks[week]) {
      weeks[week] = [];
    }
    weeks[week].push(item);
  });
  
  // Выводим по неделям
  Object.keys(weeks).sort().forEach(week => {
    result += `📌 НЕДЕЛЯ ${week}\n`;
    result += `${'-'.repeat(30)}\n`;
    
    weeks[week].forEach((item, idx) => {
      result += `\n${idx + 1}. ${item.day || 'День'} ${item.time || ''}\n`;
      result += `   Тема: ${item.topic || 'Без темы'}\n`;
      result += `   Формат: ${item.format || 'text'}\n`;
      if (item.description) {
        result += `   Описание: ${item.description}\n`;
      }
      if (item.goal) {
        result += `   Цель: ${item.goal}\n`;
      }
    });
    
    result += `\n`;
  });
  
  return result;
}

async function analyzeChannel() {
  try {
    setResult(els.analysisResult, 'Запрос анализа...');
    const data = await apiFetch('/api/analyze', { method: 'POST' });
    setResult(els.analysisResult, formatAnalysis(data));
  } catch (error) {
    setResult(els.analysisResult, `Ошибка: ${error.message}`);
  }
}

async function indexPosts() {
  try {
    setResult(els.analysisResult, 'Индексация...');
    const data = await apiFetch('/api/index', { method: 'POST' });
    setResult(els.analysisResult, `✅ Индексировано: ${data.indexed} постов\n📁 Коллекция: ${data.collection}`);
  } catch (error) {
    setResult(els.analysisResult, `Ошибка: ${error.message}`);
  }
}

function formatPosts(data) {
  if (!data.items || data.items.length === 0) {
    return `Нет постов в базе.`;
  }
  return `Показаны ${data.items.length} из ${data.total} постов:\n` + data.items
    .map((p) => `${p.post_id} | ${p.date} | ${p.views} views | ${p.media_type}\n${p.text.slice(0, 120)}...`)
    .join('\n\n');
}

function formatPlans(data) {
  if (!data.items || data.items.length === 0) {
    return 'Нет сохранённых планов.';
  }
  return `Найдено ${data.items.length} планов:\n` + data.items
    .map((plan) => `${plan.name}`)
    .join('\n');
}

async function demoData() {
  try {
    setResult(els.collectResult, 'Заполнение демонстрационными постами...');
    const data = await apiFetch('/api/demo-setup', { method: 'POST' });
    setResult(els.collectResult, `✅ ${data.message} Создано ${data.created} постов.`);
  } catch (error) {
    setResult(els.collectResult, `Ошибка: ${error.message}`);
  }
}

async function createContentPlan() {
  const weeks = parseInt(document.getElementById('planWeeks').value, 10) || 2;
  const postsPerWeek = parseInt(document.getElementById('planPostsPerWeek').value, 10) || 5;
  const instructions = document.getElementById('planInstructions').value || '';
  try {
    setResult(els.planResult, 'Генерация плана...');
    const payload = { ...getSelectedModelData(), weeks, posts_per_week: postsPerWeek, instructions };
    const data = await apiFetch('/api/content-plan', { method: 'POST', body: JSON.stringify(payload) });
    setResult(els.planResult, data);
  } catch (error) {
    setResult(els.planResult, `Ошибка: ${error.message}`);
  }
}

async function generatePost() {
  const topic = document.getElementById('postTopic').value.trim();
  const formatType = document.getElementById('postFormat').value;
  const additionalContext = document.getElementById('postContext').value.trim();
  if (!topic) {
    setResult(els.generateResult, 'Введите тему для генерации поста.');
    return;
  }
  try {
    setResult(els.generateResult, 'Генерация...');
    const payload = { ...getSelectedModelData(), topic, format_type: formatType, additional_context: additionalContext };
    const data = await apiFetch('/api/generate-post', { method: 'POST', body: JSON.stringify(payload) });
    setResult(els.generateResult, data);
  } catch (error) {
    setResult(els.generateResult, `Ошибка: ${error.message}`);
  }
}

async function generateFromPlan() {
  try {
    setResult(els.generateResult, 'Генерация постов по последнему плану...');
    const payload = { ...getSelectedModelData() };
    const data = await apiFetch('/api/generate-from-plan', { method: 'POST', body: JSON.stringify(payload) });
    setResult(els.generateResult, data);
  } catch (error) {
    setResult(els.generateResult, `Ошибка: ${error.message}`);
  }
}

async function loadPosts() {
  try {
    setResult(els.historyResult, 'Загрузка постов...');
    const data = await apiFetch('/api/posts?limit=10&offset=0');
    setResult(els.historyResult, formatPosts(data));
  } catch (error) {
    setResult(els.historyResult, `Ошибка: ${error.message}`);
  }
}

async function loadPlans() {
  try {
    setResult(els.historyResult, 'Загрузка планов...');
    const data = await apiFetch('/api/content-plans');
    setResult(els.historyResult, formatPlans(data));
  } catch (error) {
    setResult(els.historyResult, `Ошибка: ${error.message}`);
  }
}

async function loadProviders() {
  try {
    const data = await apiFetch('/api/models');
    state.providers = data.providers || [];
    els.providerSelect.innerHTML = '';
    state.providers.forEach((provider) => {
      const option = document.createElement('option');
      option.value = provider.id;
      option.textContent = provider.label;
      els.providerSelect.appendChild(option);
    });
    updateSelectOptions();
  } catch (error) {
    console.error('Ошибка загрузки провайдеров:', error);
  }
}

function initEventListeners() {
  document.getElementById('btnChannelInfo').addEventListener('click', loadChannelInfo);
  document.getElementById('btnCollect').addEventListener('click', collectPosts);
  document.getElementById('btnDemoData').addEventListener('click', demoData);
  document.getElementById('btnAnalyze').addEventListener('click', analyzeChannel);
  document.getElementById('btnIndex').addEventListener('click', indexPosts);
  document.getElementById('btnCreatePlan').addEventListener('click', createContentPlan);
  document.getElementById('btnGeneratePost').addEventListener('click', generatePost);
  document.getElementById('btnGenerateFromPlan').addEventListener('click', generateFromPlan);
  document.getElementById('btnLoadPosts').addEventListener('click', loadPosts);
  document.getElementById('btnLoadPlans').addEventListener('click', loadPlans);
  els.providerSelect.addEventListener('change', updateSelectOptions);
}

window.addEventListener('load', async () => {
  initEventListeners();
  await loadProviders();
});