// Only numeric counters, durations and fixed diagnostic labels may enter logs.
// Provider messages can contain organization IDs or user input: never log them.
function count(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isSafeInteger(n) && n >= 0 ? n : null;
}

export function durationSeconds(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  const text = String(value).trim();
  if (!text || text.length > 64) return null;
  if (/^\d+(?:\.\d+)?$/.test(text)) {
    const n = Number(text);
    return n <= 604800 ? n : null;
  }
  const match = text.match(/^(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?$/);
  if (!match || !match.slice(1).some(v => v !== undefined)) return null;
  const n = Number(match[1] || 0) * 3600 + Number(match[2] || 0) * 60 + Number(match[3] || 0);
  return n <= 604800 ? Math.round(n * 1000) / 1000 : null;
}

function header(headers, name) {
  if (typeof headers?.get === 'function') return headers.get(name);
  if (!headers || typeof headers !== 'object') return null;
  const key = Object.keys(headers).find(k => k.toLowerCase() === name);
  return key ? headers[key] : null;
}

export function rateLimitHeaders(headers) {
  const values = {
    retry_after_seconds: durationSeconds(header(headers, 'retry-after')),
    requests_limit_day: count(header(headers, 'x-ratelimit-limit-requests')),
    requests_remaining_day: count(header(headers, 'x-ratelimit-remaining-requests')),
    requests_reset_seconds: durationSeconds(header(headers, 'x-ratelimit-reset-requests')),
    tokens_limit_minute: count(header(headers, 'x-ratelimit-limit-tokens')),
    tokens_remaining_minute: count(header(headers, 'x-ratelimit-remaining-tokens')),
    tokens_reset_seconds: durationSeconds(header(headers, 'x-ratelimit-reset-tokens'))
  };
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== null));
}

export function tokenUsage(usage) {
  if (!usage || typeof usage !== 'object') return null;
  const values = {
    prompt_tokens: count(usage.prompt_tokens),
    completion_tokens: count(usage.completion_tokens),
    total_tokens: count(usage.total_tokens),
    cached_prompt_tokens: count(usage.prompt_tokens_details?.cached_tokens),
    reasoning_tokens: count(usage.completion_tokens_details?.reasoning_tokens)
  };
  const result = Object.fromEntries(Object.entries(values).filter(([, value]) => value !== null));
  return Object.keys(result).length ? result : null;
}

export function providerDiagnostic(error, aborted = false) {
  // Some Groq streaming/SSE errors carry their HTTP status in a nested cause.
  // Read only structured numeric statuses; never log a raw provider message.
  const numericStatuses = [error?.status, error?.cause?.status, error?.error?.status,
    error?.error?.error?.status, error?.response?.status].map(Number);
  const status = numericStatuses.find(n => Number.isInteger(n) && n >= 400 && n <= 599) ?? null;
  const rateLimit = rateLimitHeaders(error?.headers || error?.cause?.headers || error?.response?.headers);
  let kind = 'connection_failed', code = 'AI_CONNECTION_FAILED', retryable = true, scope = null;
  const providerType = String(error?.error?.type || error?.cause?.error?.type || '').slice(0, 70);
  const typedQuota = status === null && ['rate_limit_error', 'rate_limit_exceeded'].includes(providerType);
  if (status === 429 || typedQuota) {
    kind = 'rate_limit'; code = 'AI_RATE_LIMIT';
    const message = String(error?.error?.message || error?.cause?.error?.message || error?.message || '').slice(0, 4000);
    for (const [unit, name] of [['TPM', 'tokens_per_minute'], ['TPD', 'tokens_per_day'],
      ['RPM', 'requests_per_minute'], ['RPD', 'requests_per_day'],
      ['ITPM', 'input_tokens_per_minute'], ['OTPM', 'output_tokens_per_minute']]) {
      if (new RegExp('\\b' + unit + '\\b', 'i').test(message)) { scope = name; break; }
    }
    if (rateLimit.retry_after_seconds === undefined) {
      const delay = message.match(/try again in (\d+(?:\.\d+)?[hms](?:\d+(?:\.\d+)?[hms])*)/i);
      const seconds = durationSeconds(delay?.[1]);
      if (seconds !== null) rateLimit.retry_after_seconds = seconds;
    }
  } else if (aborted || ['APIConnectionTimeoutError', 'APIUserAbortError'].includes(error?.constructor?.name)) {
    kind = 'timeout'; code = 'AI_TIMEOUT';
  } else if (['INVALID_AI_ENVELOPE', 'EMPTY_OR_INVALID_ACTION_RESPONSE', 'OUTPUT_TOO_LARGE'].includes(error?.message)) {
    kind = 'invalid_response'; code = 'AI_RESPONSE_INVALID';
  } else if (error?.message === 'GROQ_NOT_CONFIGURED') {
    kind = 'not_configured'; retryable = false;
  } else if (error?.message === 'INVALID_MESSAGES') {
    kind = 'invalid_messages'; retryable = false;
  } else if (status === 401 || status === 403) {
    kind = 'authentication_or_permission'; retryable = false;
  } else if (status === 404) {
    kind = 'model_or_endpoint_missing'; retryable = false;
  } else if (status === 400 || status === 413) {
    kind = status === 413 ? 'request_too_large' : 'invalid_provider_request'; retryable = false;
  } else if (status === 422) {
    kind = 'unprocessable_provider_request';
  } else if (status !== null && status >= 500) {
    kind = 'provider_unavailable';
  }
  return { code, retryable, provider_status: status, provider_error_kind: kind,
    rate_limit_scope: scope, rate_limit: rateLimit };
}
