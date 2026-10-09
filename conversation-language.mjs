// Language metadata only: conversation meaning and all replies remain LLM-led.
export function conversationLanguage(history, memory = {}, fallback = 'en') {
  const users = history.filter(m => m.role === 'user');
  const latest = String(users.at(-1)?.content || '');
  const arabicLetters = text => (text.match(/\p{L}/gu) || []).some(letter => /\p{Script=Arabic}/u.test(letter));
  if (arabicLetters(latest)) return 'ar';
  if (['ar', 'en'].includes(memory.response_language)) return memory.response_language;
  for (const message of users.slice().reverse()) {
    if (arabicLetters(message.content)) return 'ar';
    if (/[A-Za-z]/.test(message.content)) return 'en';
  }
  return String(fallback).toLowerCase().startsWith('ar') ? 'ar' : 'en';
}

export function languageGuidance(language) {
  return 'CONVERSATION LANGUAGE: ' + (language === 'ar' ? 'Arabic' : 'English') +
    '. Follow user conversation language, NOT Shopify locale. For Arabic, write reply, product reasons and buttons in Arabic, ' +
    'keeping official product names unchanged. Honor explicit language/dialect requests including failed earlier turns; ' +
    'keep requested Kuwaiti dialect until changed. Understand Franco Arabic.';
}
